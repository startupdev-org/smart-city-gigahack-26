from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.api.auth import User, require_admin, require_user
from backend.db.database import Base, check_pgvector, get_db
from backend.db.models import Chunk, Document, DocumentChange, SearchLog, Source

router = APIRouter(prefix="/api", tags=["admin-feedback-cost"])


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(64))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    question: Mapped[Optional[str]] = mapped_column(Text)
    answer: Mapped[Optional[str]] = mapped_column(Text)
    useful: Mapped[bool] = mapped_column()
    reason: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FeedbackIn(BaseModel):
    question: str | None = None
    answer: str | None = None
    message_id: str | None = None
    useful: bool
    reason: str | None = Field(
        default=None,
        description="wrong_source | incomplete | incorrect | didnt_answer | outdated | other",
    )
    detail: str | None = None


@router.post("/feedback/public")
def post_feedback_public(body: FeedbackIn, db: Session = Depends(get_db)) -> dict:
    db.add(
        Feedback(
            message_id=body.message_id,
            question=body.question,
            answer=body.answer,
            useful=body.useful,
            reason=body.reason,
            detail=body.detail,
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/admin/feedback")
def admin_feedback(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = 50,
) -> list[dict]:
    rows = (
        db.query(Feedback)
        .order_by(Feedback.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": f.id,
            "question": f.question,
            "answer": getattr(f, "answer", None),
            "useful": f.useful,
            "reason": f.reason,
            "detail": getattr(f, "detail", None),
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in rows
    ]


@router.get("/admin/stats")
def admin_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    total_fb = db.query(Feedback).count()
    useful = db.query(Feedback).filter_by(useful=True).count()
    return {
        "documents": db.query(Document).count(),
        "chunks": db.query(Chunk).count(),
        "sources": db.query(Source).count(),
        "changes": db.query(DocumentChange).count(),
        "searches": db.query(SearchLog).count(),
        "feedback_total": total_fb,
        "feedback_useful_pct": round(100 * useful / total_fb, 1) if total_fb else None,
        "pgvector": check_pgvector(db),
        "last_crawl": (
            db.query(Source.last_crawled_at)
            .order_by(Source.last_crawled_at.desc().nullslast())
            .limit(1)
            .scalar()
        ),
    }


@router.get("/admin/changes")
def admin_changes(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = 20,
) -> list[dict]:
    rows = (
        db.query(DocumentChange, Document)
        .join(Document, Document.id == DocumentChange.document_id)
        .order_by(DocumentChange.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": ch.id,
            "document": doc.title,
            "url": doc.url,
            "old_hash": ch.old_hash[:12],
            "new_hash": ch.new_hash[:12],
            "diff": ch.diff,
            "detected_at": ch.detected_at.isoformat() if ch.detected_at else None,
        }
        for ch, doc in rows
    ]


@router.get("/admin/users")
def admin_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    rows = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "approved": bool(getattr(u, "approved", False)) or u.role == "admin",
            "language_pref": u.language_pref,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


class UserPatch(BaseModel):
    approved: bool | None = None
    role: str | None = Field(default=None, pattern="^(citizen|employee|admin)$")


@router.patch("/admin/users/{user_id}")
def admin_patch_user(
    user_id: int,
    body: UserPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    u = db.get(User, user_id)
    if not u:
        return {"ok": False, "error": "not found"}
    if body.approved is not None:
        u.approved = body.approved
    if body.role is not None:
        u.role = body.role
        if body.role == "admin":
            u.approved = True
    db.commit()
    return {
        "ok": True,
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "approved": bool(u.approved),
    }


@router.get("/admin/documents")
def admin_documents(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    limit: int = 50,
    q: str | None = None,
) -> list[dict]:
    query = db.query(Document)
    if q:
        like = f"%{q}%"
        query = query.filter(Document.title.ilike(like) | Document.url.ilike(like))
    rows = query.order_by(Document.id.desc()).limit(limit).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "url": d.url,
            "mime_type": d.mime_type,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.delete("/admin/documents/{doc_id}")
def admin_delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    d = db.get(Document, doc_id)
    if not d:
        return {"ok": False}
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/admin/cost")
def admin_cost(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    """Monthly cost estimate — must-have for the challenge."""
    questions = 10_000
    avg_in_tokens = 1200
    avg_out_tokens = 350
    cloud_in = 0.25
    cloud_out = 2.00
    cloud_monthly = (
        questions * avg_in_tokens / 1_000_000 * cloud_in
        + questions * avg_out_tokens / 1_000_000 * cloud_out
    )
    docs = db.query(Document).count()
    chunks = db.query(Chunk).count()
    searches = db.query(SearchLog).count()
    return {
        "assumptions": {
            "questions_per_month": questions,
            "avg_input_tokens": avg_in_tokens,
            "avg_output_tokens": avg_out_tokens,
        },
        "self_hosted": {
            "model": "qwen3:8b via Ollama",
            "hardware": "local GPU / this PC",
            "deploy_location": "Chișinău · on-prem",
            "llm_cost_usd": 0,
            "embedding_rerank": "BGE-M3 + bge-reranker-v2-m3 (local)",
            "notes": "Electricitate / uzură GPU; zero cost API LLM",
            "est_electricity_usd": 15,
        },
        "cloud_fallback": {
            "model": "GPT-5 mini (estimate)",
            "llm_cost_usd": round(cloud_monthly, 2),
            "gpu_cost_usd": 0,
            "total_usd": round(cloud_monthly, 2),
        },
        "comparison_mdl": {
            "self_hosted_approx": 270,
            "cloud_approx": round(cloud_monthly * 18, 0),
            "fx_note": "≈18 MDL / USD illustrative",
        },
        "corpus": {
            "documents": docs,
            "chunks": chunks,
            "searches_logged": searches,
            "target_documents": 5000,
            "progress_pct": min(100, round(100 * docs / 5000, 1)),
        },
        "recommendation": (
            "Prefer self-hosted pentru Q&A municipal (confidențialitate + cost 0 LLM). "
            "Cloud doar ca fallback pentru spike-uri."
        ),
    }


@router.get("/admin/health")
def admin_health(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    docs = db.query(Document).count()
    chunks = db.query(Chunk).count()
    return {
        "ok": True,
        "documents": docs,
        "chunks": chunks,
        "pgvector": check_pgvector(db),
        "target_documents": 5000,
        "progress_pct": min(100, round(100 * docs / 5000, 1)),
        "agents_tools": len(
            __import__("backend.ai.tools", fromlist=["TOOL_CATALOG"]).TOOL_CATALOG
        ),
    }


@router.get("/admin/demo-questions")
def admin_demo_questions(_: User = Depends(require_admin)) -> dict:
    """20 RO + 20 RU demo questions for judging / bilingual check."""
    from backend.data.demo_questions import DEMO_QA

    return {"count": len(DEMO_QA), "items": DEMO_QA}


@router.get("/admin/llm-settings")
def admin_get_llm_settings(_: User = Depends(require_admin)) -> dict:
    from backend.ai.runtime_settings import get_llm_runtime

    return get_llm_runtime()


class LlmSettingsPatch(BaseModel):
    provider: str | None = Field(default=None, pattern="^(local|groq)$")
    groq_model: str | None = None
    local_model: str | None = None


@router.patch("/admin/llm-settings")
def admin_patch_llm_settings(
    body: LlmSettingsPatch,
    _: User = Depends(require_admin),
) -> dict:
    from fastapi import HTTPException

    from backend.ai.runtime_settings import set_llm_runtime

    try:
        return set_llm_runtime(
            provider=body.provider,  # type: ignore[arg-type]
            groq_model=body.groq_model,
            local_model=body.local_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools")
def list_tools() -> dict:
    from backend.ai.tools import TOOL_CATALOG

    return {"tools": TOOL_CATALOG}
