from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from backend.ai.chunking import chunk_pages, sha256_text
from backend.ai.embeddings import get_embedding_service
from backend.config import get_settings
from backend.data.seed_corpus import SEED_DOCUMENTS, SEED_SOURCES, TOPIC_LINKS
from backend.db.database import SessionLocal, engine
from backend.db.models import Base, Chunk, Document, Source, TopicLink

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("init_db")

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"


def ensure_extensions(session) -> None:
    session.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
    session.commit()
    # pgvector is optional until Admin installs it (scripts/install_pgvector.ps1)
    try:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()
        logger.info("pgvector extension available.")
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("pgvector not installed yet (%s). Using JSONB embeddings.", exc)


def apply_schema_extras(session) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    # Skip extension lines already handled; run the rest statement-by-statement carefully
    session.execute(text(sql))
    session.commit()


def seed_sources(session) -> dict[str, int]:
    code_to_id: dict[str, int] = {}
    for item in SEED_SOURCES:
        existing = session.query(Source).filter_by(code=item["code"]).one_or_none()
        if existing:
            code_to_id[item["code"]] = existing.id
            continue
        src = Source(**item, language="both", active=True)
        session.add(src)
        session.flush()
        code_to_id[item["code"]] = src.id
    session.commit()
    return code_to_id


def seed_topic_links(session) -> None:
    for item in TOPIC_LINKS:
        existing = session.query(TopicLink).filter_by(topic_ro=item["topic_ro"]).one_or_none()
        if existing:
            continue
        session.add(TopicLink(**item))
    session.commit()


def ingest_documents(session, code_to_id: dict[str, int]) -> None:
    settings = get_settings()
    embedder = get_embedding_service()

    for doc in SEED_DOCUMENTS:
        content = "\n\n".join(
            f"--- Pagina {i} ---\n{page.strip()}" for i, page in enumerate(doc["pages"], 1)
        )
        content_hash = sha256_text(content)
        existing = (
            session.query(Document)
            .filter_by(title=doc["title"], content_hash=content_hash)
            .one_or_none()
        )
        if existing and existing.chunks:
            logger.info("Skip (unchanged): %s", doc["title"])
            continue

        if existing:
            session.query(Chunk).filter_by(document_id=existing.id).delete()
            existing.content = content
            existing.content_hash = content_hash
            document = existing
        else:
            document = Document(
                source_id=code_to_id.get(doc["source_code"]),
                title=doc["title"],
                url=doc.get("url"),
                language=doc.get("language", "ro"),
                content=content,
                content_hash=content_hash,
                mime_type="text/plain",
            )
            session.add(document)
            session.flush()

        pieces = chunk_pages(
            doc["pages"],
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
        texts = [p.content for p in pieces]
        vectors = embedder.embed_documents(texts)
        for piece, vector in zip(pieces, vectors, strict=True):
            session.add(
                Chunk(
                    document_id=document.id,
                    content=piece.content,
                    page=piece.page,
                    section=piece.section,
                    token_count=piece.token_count,
                    embedding=vector,
                )
            )
        session.commit()
        logger.info("Ingested %s (%d chunks)", doc["title"], len(pieces))


def main() -> None:
    logger.info("Creating tables…")
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        logger.info("Ensuring extensions…")
        ensure_extensions(session)
        logger.info("Seeding sources…")
        code_to_id = seed_sources(session)
        seed_topic_links(session)
        logger.info("Ingesting seed documents + embeddings…")
        ingest_documents(session, code_to_id)
        try:
            apply_schema_extras(session)
            logger.info("Indexes/triggers applied.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema extras partial/skipped: %s", exc)
            session.rollback()

    logger.info("Done. Database ready for hybrid search.")


if __name__ == "__main__":
    main()
