from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from .db import get_db
from .models import Organization, OrganizationMembership, FileShare, StoredFile, User
from .security import current_user

router = APIRouter(prefix="/organizations", tags=["organizations and sharing"])

class OrganizationInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)

class MemberInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    role: str = "member"

class ShareInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    expires_at: datetime | None = None

def membership(db: Session, organization_id: str, user_id: str):
    return db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.status == "active"))

def require_admin(db: Session, organization_id: str, user_id: str):
    member = membership(db, organization_id, user_id)
    if not member or member.role != "admin":
        raise HTTPException(403, "Organization admin permission required")
    return member

def grant_active(db: Session, file_id: str, organization_id: str, user_id: str):
    now = datetime.now(timezone.utc)
    return db.scalar(select(FileShare).join(
        OrganizationMembership,
        and_(OrganizationMembership.organization_id == FileShare.organization_id,
             OrganizationMembership.user_id == FileShare.grantee_user_id,
             OrganizationMembership.status == "active")
    ).where(FileShare.file_id == file_id,
            FileShare.organization_id == organization_id,
            FileShare.grantee_user_id == user_id,
            FileShare.permission == "download",
            FileShare.revoked_at.is_(None),
            (FileShare.expires_at.is_(None) | (FileShare.expires_at > now))))

def can_download_shared(db: Session, file_id: str, user_id: str):
    now = datetime.now(timezone.utc)
    return db.scalar(select(FileShare.id).join(
        OrganizationMembership,
        and_(OrganizationMembership.organization_id == FileShare.organization_id,
             OrganizationMembership.user_id == FileShare.grantee_user_id,
             OrganizationMembership.status == "active")
    ).where(FileShare.file_id == file_id, FileShare.grantee_user_id == user_id,
            FileShare.permission == "download", FileShare.revoked_at.is_(None),
            (FileShare.expires_at.is_(None) | (FileShare.expires_at > now)))) is not None

@router.post("", status_code=201)
def create_organization(body: OrganizationInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = Organization(id=str(uuid.uuid4()), name=body.name.strip(), created_by=user.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="admin", status="active"))
    db.commit()
    return {"id": org.id, "name": org.name, "role": "admin"}

@router.get("")
def list_organizations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Organization, OrganizationMembership.role).join(
        OrganizationMembership, OrganizationMembership.organization_id == Organization.id
    ).where(OrganizationMembership.user_id == user.id, OrganizationMembership.status == "active")).all()
    return [{"id": org.id, "name": org.name, "role": role} for org, role in rows]

@router.post("/{organization_id}/members", status_code=201)
def add_member(organization_id: str, body: MemberInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(db, organization_id, user.id)
    if body.role not in {"member", "admin"}:
        raise HTTPException(422, "Role must be member or admin")
    target = db.scalar(select(User).where(User.username == body.username.lower()))
    if not target:
        raise HTTPException(404, "That username is not registered yet")
    existing = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == target.id))
    if existing:
        existing.role, existing.status = body.role, "active"
    else:
        db.add(OrganizationMembership(organization_id=organization_id, user_id=target.id,
                                      role=body.role, status="active"))
    db.commit()
    return {"organization_id": organization_id, "username": target.username, "role": body.role, "status": "active"}

@router.get("/{organization_id}/members")
def list_members(organization_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not membership(db, organization_id, user.id):
        raise HTTPException(404, "Organization not found")
    rows = db.execute(select(User.username, User.email, OrganizationMembership.role, OrganizationMembership.status)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.organization_id == organization_id)).all()
    return [{"username": username, "email": email, "role": role, "status": status} for username, email, role, status in rows]

@router.post("/{organization_id}/files/{file_id}/share", status_code=201)
def share_file(organization_id: str, file_id: str, body: ShareInput,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_member = membership(db, organization_id, user.id)
    if not org_member:
        raise HTTPException(404, "Organization not found")
    record = db.get(StoredFile, file_id)
    if not record:
        raise HTTPException(404, "File not found")
    if record.organization_id not in (None, organization_id):
        raise HTTPException(409, "File belongs to another organization")
    if record.organization_id is None:
        if record.owner_id != user.id and org_member.role != "admin":
            raise HTTPException(403, "Only the file owner or an organization admin can add it")
        record.organization_id = organization_id
    elif record.owner_id != user.id and org_member.role != "admin":
        raise HTTPException(403, "Only the file owner or organization admin can share this file")
    target = db.scalar(select(User).where(User.username == body.username.lower()))
    if not target:
        raise HTTPException(404, "Recipient must register a username and join the organization first")
    if not membership(db, organization_id, target.id):
        raise HTTPException(403, "Recipient is not an active organization member")
    if target.id == user.id:
        raise HTTPException(422, "You already have access to your own file")
    if body.expires_at:
        expiry = body.expires_at
        if expiry.tzinfo is None:
            raise HTTPException(422, "expires_at must include a timezone")
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(422, "expires_at must be in the future")
    else:
        expiry = None
    share = db.scalar(select(FileShare).where(
        FileShare.file_id == file_id, FileShare.grantee_user_id == target.id,
        FileShare.organization_id == organization_id, FileShare.revoked_at.is_(None)))
    if share:
        share.expires_at, share.granted_by, share.permission = expiry, user.id, "download"
    else:
        share = FileShare(file_id=file_id, organization_id=organization_id,
                          grantee_user_id=target.id, granted_by=user.id,
                          permission="download", expires_at=expiry)
        db.add(share)
    db.commit()
    return {"share_id": share.id, "file_id": file_id, "recipient": target.username,
            "permission": "download", "expires_at": expiry}

@router.get("/{organization_id}/shared-with-me")
def shared_with_me(organization_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not membership(db, organization_id, user.id):
        raise HTTPException(404, "Organization not found")
    now = datetime.now(timezone.utc)
    rows = db.execute(select(StoredFile, FileShare).join(FileShare, FileShare.file_id == StoredFile.id)
        .join(OrganizationMembership, and_(OrganizationMembership.organization_id == FileShare.organization_id,
             OrganizationMembership.user_id == FileShare.grantee_user_id, OrganizationMembership.status == "active"))
        .where(FileShare.organization_id == organization_id,
               FileShare.grantee_user_id == user.id,
               FileShare.permission == "download",
               FileShare.revoked_at.is_(None),
               (FileShare.expires_at.is_(None) | (FileShare.expires_at > now))))
    return [{"id": f.id, "name": f.original_name, "size": f.original_size,
             "fragment_count": f.fragment_count, "share_id": s.id}
            for f, s in rows]

@router.delete("/{organization_id}/shares/{share_id}", status_code=204)
def revoke_share(organization_id: str, share_id: str,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_member = membership(db, organization_id, user.id)
    if not org_member:
        raise HTTPException(404, "Organization not found")
    share = db.scalar(select(FileShare).where(FileShare.id == share_id,
        FileShare.organization_id == organization_id, FileShare.revoked_at.is_(None)))
    if not share:
        raise HTTPException(404, "Share not found")
    record = db.get(StoredFile, share.file_id)
    if user.id != share.granted_by and user.id != (record.owner_id if record else None) and org_member.role != "admin":
        raise HTTPException(403, "Only the grantor, file owner, or organization admin can revoke access")
    share.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return None
