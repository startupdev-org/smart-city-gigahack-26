from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.api.auth import User, require_approved, require_user
from backend.db.database import Base, get_db

router = APIRouter(prefix="/api/chats", tags=["chats"])


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Chat nou")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(32))
    sources_json: Mapped[Optional[str]] = mapped_column(Text)
    conflicts_json: Mapped[Optional[str]] = mapped_column(Text)
    next_action_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SessionOut(BaseModel):
    id: int
    title: str
    updated_at: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    status: str | None = None
    sources: list | None = None
    conflicts: list | None = None
    next_action: dict | None = None
    created_at: str | None = None


class SessionCreate(BaseModel):
    title: str = Field(default="Chat nou", max_length=255)


def ensure_session(
    db: Session, user_id: int, session_id: int | None, title: str = "Chat nou"
) -> int:
    if session_id:
        s = db.get(ChatSession, session_id)
        if s and s.user_id == user_id:
            s.updated_at = datetime.utcnow()
            if s.title in ("Chat nou", "New chat") and title:
                s.title = title[:80]
            db.commit()
            return s.id
    s = ChatSession(user_id=user_id, title=(title or "Chat nou")[:80])
    db.add(s)
    db.commit()
    db.refresh(s)
    return s.id


def add_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    *,
    status: str | None = None,
    sources: list | None = None,
    conflicts: list | None = None,
    next_action: dict | None = None,
) -> None:
    db.add(
        ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            status=status,
            sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
            conflicts_json=json.dumps(conflicts, ensure_ascii=False) if conflicts else None,
            next_action_json=(
                json.dumps(next_action, ensure_ascii=False) if next_action else None
            ),
        )
    )
    s = db.get(ChatSession, session_id)
    if s:
        s.updated_at = datetime.utcnow()
    db.commit()


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[SessionOut]:
    rows = (
        db.query(ChatSession)
        .filter_by(user_id=user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(100)
        .all()
    )
    return [
        SessionOut(
            id=r.id,
            title=r.title,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in rows
    ]


@router.post("", response_model=SessionOut)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_approved),
) -> SessionOut:
    s = ChatSession(user_id=user.id, title=body.title[:80])
    db.add(s)
    db.commit()
    db.refresh(s)
    return SessionOut(
        id=s.id,
        title=s.title,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
    )


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def get_messages(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> list[MessageOut]:
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    rows = (
        db.query(ChatMessage)
        .filter_by(session_id=session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    out = []
    for r in rows:
        out.append(
            MessageOut(
                id=r.id,
                role=r.role,
                content=r.content,
                status=r.status,
                sources=json.loads(r.sources_json) if r.sources_json else None,
                conflicts=json.loads(r.conflicts_json) if r.conflicts_json else None,
                next_action=json.loads(r.next_action_json) if r.next_action_json else None,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )
    return out


@router.delete("/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    s = db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    db.delete(s)
    db.commit()
    return {"ok": True}
