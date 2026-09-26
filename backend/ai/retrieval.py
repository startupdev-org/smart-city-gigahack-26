from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.ai.embeddings import get_embedding_service
from backend.ai.reranker import get_reranker_service
from backend.config import get_settings
from backend.db.models import SearchLog

logger = logging.getLogger(__name__)

# Truncate passages before expensive cross-encoder (big win on CPU).
_RERANK_CHARS = 280
_QUERY_CACHE: dict[str, tuple[float, list]] = {}
_QUERY_CACHE_TTL = 90.0
_QUERY_CACHE_MAX = 64


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    document_url: str | None
    content: str
    page: int | None
    section: str | None
    dense_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None


def _detect_language(query: str) -> str:
    cyr = sum(1 for c in query if "\u0400" <= c <= "\u04FF")
    lat = sum(1 for c in query if c.isalpha() and not ("\u0400" <= c <= "\u04FF"))
    if cyr > lat:
        return "ru"
    return "ro"


def _cosine_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return matrix @ query_vec


@lru_cache(maxsize=1)
def _pgvector_ready(db_url: str) -> bool:
    """Cached once per process — avoid information_schema on every request."""
    from backend.db.database import SessionLocal

    with SessionLocal() as db:
        has_col = db.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name='chunks' AND column_name='embedding_vec'
                """
            )
        ).first()
        has_ext = db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname='vector'")
        ).first()
        return bool(has_col and has_ext)


class HybridRetriever:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.embeddings = get_embedding_service()
        self.reranker = get_reranker_service()

    def search(self, query: str, *, top_k: int | None = None) -> list[RetrievedChunk]:
        t0 = time.perf_counter()
        settings = self.settings
        k = top_k or settings.rerank_top_k
        language = _detect_language(query)
        cache_key = f"{language}|{k}|{query.strip().lower()}"
        cached = _QUERY_CACHE.get(cache_key)
        if cached and (time.perf_counter() - cached[0]) < _QUERY_CACHE_TTL:
            return cached[1]

        t_dense = time.perf_counter()
        qvec = np.asarray(self.embeddings.embed_query(query), dtype=np.float32)
        embed_ms = (time.perf_counter() - t_dense) * 1000

        use_pgvector = _pgvector_ready(settings.database_url)

        def dense_search() -> list[RetrievedChunk]:
            hits: list[RetrievedChunk] = []
            if use_pgvector:
                qvec_literal = "[" + ",".join(f"{x:.6f}" for x in qvec.tolist()) + "]"
                rows = self.db.execute(
                    text(
                        """
                        SELECT c.id, c.document_id, d.title, d.url, c.content, c.page, c.section,
                               1 - (c.embedding_vec <=> CAST(:qvec AS vector)) AS score
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE c.embedding_vec IS NOT NULL
                        ORDER BY c.embedding_vec <=> CAST(:qvec AS vector)
                        LIMIT :lim
                        """
                    ),
                    {"qvec": qvec_literal, "lim": settings.retrieve_dense_k},
                ).mappings().all()
                for row in rows:
                    hits.append(
                        RetrievedChunk(
                            chunk_id=row["id"],
                            document_id=row["document_id"],
                            document_title=row["title"],
                            document_url=row["url"],
                            content=row["content"],
                            page=row["page"],
                            section=row["section"],
                            dense_score=float(row["score"] or 0),
                        )
                    )
            else:
                rows = self.db.execute(
                    text(
                        """
                        SELECT c.id, c.document_id, d.title, d.url, c.content, c.page, c.section,
                               c.embedding
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE c.embedding IS NOT NULL
                        """
                    )
                ).mappings().all()
                if rows:
                    matrix = np.asarray(
                        [row["embedding"] for row in rows], dtype=np.float32
                    )
                    scores = _cosine_scores(qvec, matrix)
                    top_idx = np.argsort(-scores)[: settings.retrieve_dense_k]
                    for i in top_idx:
                        row = rows[int(i)]
                        hits.append(
                            RetrievedChunk(
                                chunk_id=row["id"],
                                document_id=row["document_id"],
                                document_title=row["title"],
                                document_url=row["url"],
                                content=row["content"],
                                page=row["page"],
                                section=row["section"],
                                dense_score=float(scores[int(i)]),
                            )
                        )
            return hits

        def lexical_search() -> list[dict]:
            return (
                self.db.execute(
                    text(
                        """
                        SELECT c.id, c.document_id, d.title, d.url, c.content, c.page, c.section,
                               ts_rank_cd(c.tsv, plainto_tsquery('simple', unaccent(:q))) AS score
                        FROM chunks c
                        JOIN documents d ON d.id = c.document_id
                        WHERE c.tsv @@ plainto_tsquery('simple', unaccent(:q))
                        ORDER BY score DESC
                        LIMIT :lim
                        """
                    ),
                    {"q": query, "lim": settings.retrieve_lexical_k},
                )
                .mappings()
                .all()
            )

        t_ret = time.perf_counter()
        # Same Session isn't fully thread-safe — run sequential but lean queries.
        # Parallelize only if two sessions; keep simple + fast with small LIMITs.
        dense_hits = dense_search()
        dense_ms = (time.perf_counter() - t_ret) * 1000 + embed_ms

        t_lex = time.perf_counter()
        lexical_rows = lexical_search()
        lexical_ms = (time.perf_counter() - t_lex) * 1000

        merged: dict[int, RetrievedChunk] = {h.chunk_id: h for h in dense_hits}
        for row in lexical_rows:
            if row["id"] in merged:
                merged[row["id"]].lexical_score = float(row["score"] or 0)
            else:
                merged[row["id"]] = RetrievedChunk(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    document_title=row["title"],
                    document_url=row["url"],
                    content=row["content"],
                    page=row["page"],
                    section=row["section"],
                    lexical_score=float(row["score"] or 0),
                )

        candidates = list(merged.values())
        if not candidates:
            self._log(query, language, dense_ms, lexical_ms, 0, time.perf_counter() - t0, 0)
            return []

        # Cap candidates before rerank (hybrid can grow); keep best by dense/lex
        if len(candidates) > settings.rerank_candidates:
            candidates.sort(
                key=lambda c: max(c.dense_score or 0, (c.lexical_score or 0) * 2),
                reverse=True,
            )
            candidates = candidates[: settings.rerank_candidates]

        t_rr = time.perf_counter()
        passages = [(c.content or "")[:_RERANK_CHARS] for c in candidates]
        ranked = self.reranker.rerank(query, passages, top_k=k)
        rerank_ms = (time.perf_counter() - t_rr) * 1000

        results: list[RetrievedChunk] = []
        for idx, score in ranked:
            item = candidates[idx]
            item.rerank_score = float(score)
            results.append(item)

        total_ms = (time.perf_counter() - t0) * 1000
        self._log(query, language, dense_ms, lexical_ms, rerank_ms, total_ms / 1000, len(results))
        logger.info(
            "search embed+dense=%.0fms lex=%.0fms rerank=%.0fms total=%.0fms hits=%d cand=%d",
            dense_ms,
            lexical_ms,
            rerank_ms,
            total_ms,
            len(results),
            len(candidates),
        )
        _QUERY_CACHE[cache_key] = (time.perf_counter(), results)
        if len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
            # drop oldest
            oldest = sorted(_QUERY_CACHE.items(), key=lambda x: x[1][0])[:16]
            for key, _ in oldest:
                _QUERY_CACHE.pop(key, None)
        return results

    def _log(
        self,
        query: str,
        language: str,
        dense_ms: float,
        lexical_ms: float,
        rerank_ms: float,
        total_s: float,
        count: int,
    ) -> None:
        self.db.add(
            SearchLog(
                query=query,
                language=language,
                dense_ms=dense_ms,
                lexical_ms=lexical_ms,
                rerank_ms=rerank_ms,
                total_ms=total_s * 1000,
                result_count=count,
            )
        )
        self.db.commit()
