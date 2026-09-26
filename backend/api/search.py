from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.ai.retrieval import HybridRetriever
from backend.db.database import get_db

router = APIRouter(prefix="/api", tags=["search"])


class SearchHit(BaseModel):
    chunk_id: int
    document_id: int
    document: str
    url: str | None = None
    page: int | None = None
    section: str | None = None
    quote: str
    dense_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    language: str
    results: list[SearchHit] = Field(default_factory=list)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "civic-ai"}


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=2, description="Citizen / employee question"),
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> SearchResponse:
    retriever = HybridRetriever(db)
    hits = retriever.search(q, top_k=top_k)
    language = "ru" if any("\u0400" <= c <= "\u04FF" for c in q) else "ro"
    return SearchResponse(
        query=q,
        language=language,
        results=[
            SearchHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                document=h.document_title,
                url=h.document_url,
                page=h.page,
                section=h.section,
                quote=h.content[:600],
                dense_score=h.dense_score,
                lexical_score=h.lexical_score,
                rerank_score=h.rerank_score,
            )
            for h in hits
        ],
    )
