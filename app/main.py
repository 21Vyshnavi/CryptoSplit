import os, uuid, hashlib
from pathlib import Path
from urllib.parse import quote
from typing import Annotated
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db, migrate_company_sharing
from .models import User, StoredFile, Fragment
from .security import current_user, hash_password, verify_password, make_token
from .crypto import wrap_key, unwrap_key, encrypt_fragment, decrypt_fragment
from .storage import put_object, get_object, delete_object, init_storage
from .organizations import router as organizations_router, can_download_shared

app = FastAPI(title="CryptoSplit API", version="1.0.0", description="Encrypted, fragmented file storage demo API")
if settings.key_encryption_backend not in {"rsa", "kms"}:
    raise RuntimeError("KEY_ENCRYPTION_BACKEND must be rsa or kms")
if settings.key_encryption_backend == "kms" and not settings.kms_key_id:
    raise RuntimeError("KMS_KEY_ID is required when KEY_ENCRYPTION_BACKEND=kms")
init_storage()
Base.metadata.create_all(bind=engine)  # Demo bootstrap; use Alembic migrations for managed deployments.
migrate_company_sharing()
app.include_router(organizations_router)

class Credentials(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    password: str = Field(min_length=12, max_length=256)

class LoginCredentials(BaseModel):
    identity: str = Field(min_length=3, max_length=254)
    password: str

class UsernameInput(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/auth/register", status_code=201)
def register(body: Credentials, db: Session = Depends(get_db)):
    email = body.email.lower()
    username = body.username.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email is already registered")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Username is already taken")
    user = User(email=email, username=username, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email or username is already registered")
    db.refresh(user)
    return {"id": user.id, "email": user.email, "username": user.username}

@app.post("/auth/login")
def login(body: LoginCredentials, db: Session = Depends(get_db)):
    identity = body.identity.strip().lower()
    user = db.scalar(select(User).where((User.email == identity) | (User.username == identity)))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": make_token(user.id), "token_type": "bearer", "expires_in": settings.jwt_minutes * 60}

@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "username": user.username}

@app.put("/auth/username")
def set_username(body: UsernameInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    username = body.username.lower()
    existing = db.scalar(select(User).where(User.username == username, User.id != user.id))
    if existing:
        raise HTTPException(409, "Username is already taken")
    user.username = username
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username is already taken")
    return {"username": user.username}

@app.post("/files", status_code=201)
async def upload(file: Annotated[UploadFile, File()], user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Upload exceeds configured size limit")
    file_id = str(uuid.uuid4())
    chunk_size = max(64 * 1024, settings.fragment_bytes)
    chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)] or [b""]
    aes_key = os.urandom(32)
    safe_name = Path(file.filename or "upload.bin").name[:255]
    wrapped_key, wrapped_key_key_id = wrap_key(aes_key)
    record = StoredFile(id=file_id, owner_id=user.id, original_name=safe_name,
                        content_type="application/octet-stream",
                        original_size=len(data), fragment_count=len(chunks), wrapped_key=wrapped_key,
                        wrapped_key_key_id=wrapped_key_key_id)
    paths = []
    try:
        db.add(record); db.flush()
        for i, chunk in enumerate(chunks):
            nonce, ciphertext, digest = encrypt_fragment(aes_key, chunk, file_id, i, len(chunks))
            storage_key = f"{file_id}/{i:08d}.bin"
            put_object(storage_key, ciphertext)
            paths.append(storage_key)
            db.add(Fragment(file_id=file_id, fragment_index=i, storage_key=storage_key,
                            nonce=nonce, sha256=digest, ciphertext_size=len(ciphertext)))
        db.commit()
    except Exception:
        db.rollback()
        for storage_key in paths:
            try: delete_object(storage_key)
            except Exception: pass
        raise
    return {"id": record.id, "name": record.original_name, "size": record.original_size,
            "fragment_count": record.fragment_count, "status": "stored",
            "data_encryption": "AES-256-GCM", "key_wrapping": "RSA-OAEP-SHA-256"}

@app.get("/files")
def list_files(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(StoredFile).where(StoredFile.owner_id == user.id).order_by(StoredFile.created_at.desc())).all()
    return [{"id": f.id, "name": f.original_name, "size": f.original_size,
             "fragment_count": f.fragment_count, "created_at": f.created_at} for f in rows]

@app.get("/files/{file_id}/download")
def download(file_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(StoredFile).where(StoredFile.id == file_id))
    if record and record.owner_id != user.id and not can_download_shared(db, file_id, user.id):
        record = None
    if not record: raise HTTPException(404, "File not found")
    pieces = []
    try:
        key = unwrap_key(record.wrapped_key, record.wrapped_key_key_id)
        if len(record.fragments) != record.fragment_count: raise ValueError("Fragment set incomplete")
        for frag in record.fragments:
            expected_key = f"{record.id}/{frag.fragment_index:08d}.bin"
            if frag.storage_key != expected_key: raise ValueError("Invalid fragment reference")
            ciphertext = get_object(frag.storage_key)
            if len(ciphertext) != frag.ciphertext_size or hashlib.sha256(ciphertext).hexdigest() != frag.sha256:
                raise ValueError("Ciphertext integrity check failed")
            pieces.append(decrypt_fragment(key, frag.nonce, ciphertext, record.id, frag.fragment_index, record.fragment_count))
        content = b"".join(pieces)
        if len(content) != record.original_size: raise ValueError("Reconstructed size mismatch")
    except Exception:
        raise HTTPException(500, "File verification or reconstruction failed")
    safe_name = quote(record.original_name.replace('\r', '').replace('\n', '').replace('"', '').replace('\\', ''), safe="")
    return StreamingResponse(iter([content]), media_type=record.content_type,
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}", "X-Content-Type-Options": "nosniff"})

@app.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(StoredFile).where(StoredFile.id == file_id, StoredFile.owner_id == user.id))
    if not record: raise HTTPException(404, "File not found")
    keys = [f.storage_key for f in record.fragments]
    db.delete(record); db.commit()
    for key in keys:
        try: delete_object(key)
        except Exception: pass
    return None

app.mount("/", StaticFiles(directory="app/static", html=True), name="web")
