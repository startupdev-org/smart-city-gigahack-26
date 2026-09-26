"""Migrate chunks.embedding JSONB → pgvector column embedding_vec."""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.db.database import SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_pgvector")


def main() -> None:
    with SessionLocal() as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()

        session.execute(
            text(
                """
                ALTER TABLE chunks
                ADD COLUMN IF NOT EXISTS embedding_vec vector(1024)
                """
            )
        )
        session.commit()

        rows = session.execute(
            text("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL")
        ).mappings().all()
        logger.info("Migrating %d embeddings…", len(rows))
        for row in rows:
            vec = row["embedding"]
            if not vec:
                continue
            literal = "[" + ",".join(str(float(x)) for x in vec) + "]"
            session.execute(
                text(
                    "UPDATE chunks SET embedding_vec = CAST(:v AS vector) WHERE id = :id"
                ),
                {"v": literal, "id": row["id"]},
            )
        session.commit()

        session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding_vec_hnsw
                ON chunks USING hnsw (embedding_vec vector_cosine_ops)
                """
            )
        )
        session.commit()
        logger.info("Done. pgvector column + HNSW index ready.")


if __name__ == "__main__":
    main()
