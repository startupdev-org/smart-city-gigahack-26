from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from backend.ai.chunking import chunk_pages, chunk_text, sha256_text
from backend.ai.embeddings import get_embedding_service
from backend.config import get_settings
from backend.crawler.allowlist import registrable_host, source_code_from_url
from backend.db.models import Chunk, Document, DocumentChange, Source

logger = logging.getLogger(__name__)


def ensure_source(
    session: Session,
    *,
    url: str,
    name: str | None = None,
    category: str = "discovered",
    priority: str = "P2",
    type_: str = "portal",
) -> Source:
    code = source_code_from_url(url)
    existing = session.query(Source).filter_by(code=code).one_or_none()
    if existing:
        return existing
    # also match by exact url
    existing = session.query(Source).filter_by(url=url).one_or_none()
    if existing:
        return existing

    host = registrable_host(url)
    src = Source(
        code=code,
        name=name or host or url,
        url=url,
        type=type_,
        category=category,
        language="both",
        priority=priority,
        active=True,
    )
    session.add(src)
    session.flush()
    logger.info("Auto-added source [%s] %s", src.priority, src.url)
    return src


def mark_source_crawled(session: Session, source: Source) -> None:
    source.last_crawled_at = datetime.now(timezone.utc)
    session.add(source)


def ingest_text_document(
    session: Session,
    *,
    source: Source,
    title: str,
    url: str,
    text: str,
    mime_type: str,
    pages: list[str] | None = None,
) -> Document | None:
    text = (text or "").strip()
    try:
        from backend.crawler.html_parser import scrub_indexed_text

        text = scrub_indexed_text(text)
    except Exception:  # noqa: BLE001
        pass
    if len(text) < 40:
        logger.info("Skip too-short content: %s", url)
        return None

    content_hash = sha256_text(text)
    existing = session.query(Document).filter_by(url=url).one_or_none()

    if existing and existing.content_hash == content_hash:
        logger.info("Unchanged: %s", title[:80])
        return existing

    settings = get_settings()
    embedder = get_embedding_service()

    if existing:
        session.add(
            DocumentChange(
                document_id=existing.id,
                old_hash=existing.content_hash,
                new_hash=content_hash,
                diff=f"Content changed for {url}",
            )
        )
        session.query(Chunk).filter_by(document_id=existing.id).delete()
        existing.title = title[:512]
        existing.content = text
        existing.content_hash = content_hash
        existing.mime_type = mime_type
        existing.source_id = source.id
        document = existing
        logger.info("Updated document: %s", title[:80])
    else:
        document = Document(
            source_id=source.id,
            title=title[:512],
            url=url,
            language="ro",
            content=text,
            content_hash=content_hash,
            mime_type=mime_type,
        )
        session.add(document)
        session.flush()
        logger.info("New document: %s", title[:80])

    if pages:
        pieces = chunk_pages(
            pages,
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    else:
        pieces = chunk_text(
            text,
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )

    if not pieces:
        session.commit()
        return document

    vectors = embedder.embed_documents([p.content for p in pieces])
    has_vec = False
    try:
        from sqlalchemy import text as sql_text

        has_vec = (
            session.execute(
                sql_text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='chunks' AND column_name='embedding_vec'"
                )
            ).first()
            is not None
        )
    except Exception:  # noqa: BLE001
        has_vec = False

    for piece, vector in zip(pieces, vectors, strict=True):
        chunk = Chunk(
            document_id=document.id,
            content=piece.content,
            page=piece.page,
            section=piece.section,
            token_count=piece.token_count,
            embedding=vector,
        )
        session.add(chunk)
        session.flush()
        if has_vec:
            literal = "[" + ",".join(str(float(x)) for x in vector) + "]"
            session.execute(
                sql_text(
                    "UPDATE chunks SET embedding_vec = CAST(:v AS vector) WHERE id = :id"
                ),
                {"v": literal, "id": chunk.id},
            )
    session.commit()
    logger.info("Indexed %d chunks ← %s", len(pieces), urlparse(url).path[:60])
    return document
