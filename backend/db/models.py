from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(64), default="portal")
    category: Mapped[str] = mapped_column(String(128), default="general")
    language: Mapped[str] = mapped_column(String(16), default="both")
    priority: Mapped[str] = mapped_column(String(8), default="P1")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    documents: Mapped[list[Document]] = relationship(back_populates="source")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"))
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="ro")
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(128), default="text/plain")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[Optional[Source]] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    changes: Mapped[list[DocumentChange]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(128))
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    # JSONB until pgvector is installed (run scripts/install_pgvector.ps1 as Admin)
    embedding = mapped_column(JSONB)
    tsv = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


class DocumentChange(Base):
    __tablename__ = "document_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    old_hash: Mapped[str] = mapped_column(String(64))
    new_hash: Mapped[str] = mapped_column(String(64))
    diff: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="changes")


class TopicLink(Base):
    __tablename__ = "topic_links"
    __table_args__ = (UniqueConstraint("topic_ro", name="uq_topic_ro"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_ro: Mapped[str] = mapped_column(String(128))
    topic_ru: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    contact_label: Mapped[Optional[str]] = mapped_column(String(255))
    contact_value: Mapped[Optional[str]] = mapped_column(String(255))


class SearchLog(Base):
    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    language: Mapped[Optional[str]] = mapped_column(String(8))
    dense_ms: Mapped[Optional[float]] = mapped_column(Float)
    lexical_ms: Mapped[Optional[float]] = mapped_column(Float)
    rerank_ms: Mapped[Optional[float]] = mapped_column(Float)
    total_ms: Mapped[Optional[float]] = mapped_column(Float)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
