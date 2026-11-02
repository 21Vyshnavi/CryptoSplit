from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

password_hash = PasswordHash.recommended()
bearer = HTTPBearer()

def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise HTTPException(422, "Password must be between 12 and 256 characters")
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try: return password_hash.verify(password, hashed)
    except Exception: return False

def make_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iss": settings.jwt_issuer, "iat": now,
                       "exp": now + timedelta(minutes=settings.jwt_minutes)}, settings.jwt_secret, algorithm="HS256")

def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired credentials",
                          headers={"WWW-Authenticate": "Bearer"})
    try:
        data = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer)
        user = db.get(User, data.get("sub"))
    except (jwt.PyJWTError, TypeError):
        raise error
    if user is None: raise error
    return user
