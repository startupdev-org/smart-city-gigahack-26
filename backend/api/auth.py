from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.config import get_settings
from backend.db.database import Base, get_db

security = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="citizen")
    language_pref: Mapped[str] = mapped_column(String(8), default="ro")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefreshSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    refresh_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    language_pref: str = "ro"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str
    approved: bool = False


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, hashed: str) -> bool:
    try:
        salt, digest = hashed.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return secrets.compare_digest(check, digest)


def _make_access(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    db: Session = Depends(get_db),
) -> Optional[User]:
    if not creds:
        return None
    settings = get_settings()
    try:
        data = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(data["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    return db.get(User, user_id)


def require_user(user: Annotated[Optional[User], Depends(get_current_user)]) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
    return user


def require_approved(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role == "admin" or bool(getattr(user, "approved", False)):
        return user
    raise HTTPException(
        status_code=403,
        detail="Contul așteaptă aprobarea administratorului pentru a folosi chat-ul.",
    )


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    if db.query(User).filter_by(email=body.email.lower()).first():
        raise HTTPException(400, "Email already registered")
    role = "citizen"
    approved = False
    if db.query(User).count() == 0:
        role = "admin"
        approved = True
    user = User(
        email=body.email.lower(),
        password_hash=_hash_password(body.password),
        role=role,
        language_pref=body.language_pref,
        approved=approved,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(
        access_token=_make_access(user),
        role=user.role,
        email=user.email,
        approved=bool(user.approved) or user.role == "admin",
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter_by(email=body.email.lower()).first()
    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return TokenOut(
        access_token=_make_access(user),
        role=user.role,
        email=user.email,
        approved=bool(user.approved) or user.role == "admin",
    )


@router.get("/me")
def me(user: Annotated[User, Depends(require_user)]) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "language_pref": user.language_pref,
        "approved": bool(user.approved) or user.role == "admin",
    }


def seed_admin(db: Session) -> None:
    admin = db.query(User).filter_by(email="admin@civic.ai").first()
    if admin:
        if not getattr(admin, "approved", True):
            admin.approved = True
            db.commit()
        return
    db.add(
        User(
            email="admin@civic.ai",
            password_hash=_hash_password("admin123"),
            role="admin",
            language_pref="ro",
            approved=True,
        )
    )
    db.commit()
