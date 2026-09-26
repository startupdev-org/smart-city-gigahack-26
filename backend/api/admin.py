from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.api.auth import (
    User,
    _permissions_for,
    require_admin,
    require_staff,
)
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


@router.get("/admin/me")
def admin_me(user: User = Depends(require_staff)) -> dict:
    return {
        "email": user.email,
        "role": user.role,
        "permissions": _permissions_for(user.role),
    }


@router.get("/admin/feedback")
def admin_feedback(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
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
            "detail": f.detail,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in rows
    ]


@router.get("/admin/stats")
def admin_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> dict:
    total_fb = db.query(Feedback).count()
    useful = db.query(Feedback).filter_by(useful=True).count()
    users_n = db.query(User).count()
    approved_n = (
        db.query(User)
        .filter((User.approved.is_(True)) | (User.role.in_(["admin", "manager"])))
        .count()
    )
    return {
        "documents": db.query(Document).count(),
        "chunks": db.query(Chunk).count(),
        "sources": db.query(Source).count(),
        "changes": db.query(DocumentChange).count(),
        "searches": db.query(SearchLog).count(),
        "users_total": users_n,
        "users_approved": approved_n,
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
            "approved": bool(getattr(u, "approved", False))
            or u.role in ("admin", "manager"),
            "language_pref": u.language_pref,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


class UserPatch(BaseModel):
    approved: bool | None = None
    role: str | None = Field(
        default=None, pattern="^(citizen|employee|manager|admin)$"
    )


@router.patch("/admin/users/{user_id}")
def admin_patch_user(
    user_id: int,
    body: UserPatch,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> dict:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.approved is not None:
        u.approved = body.approved
    if body.role is not None:
        if u.id == actor.id and body.role != "admin":
            raise HTTPException(400, "Nu poți elimina propriul rol de admin")
        u.role = body.role
        if body.role in ("admin", "manager"):
            u.approved = True
    db.commit()
    return {
        "ok": True,
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "approved": bool(u.approved) or u.role in ("admin", "manager"),
    }


@router.get("/admin/documents")
def admin_documents(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
    limit: int = 80,
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
            "source_id": d.source_id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.delete("/admin/documents/{doc_id}")
def admin_delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> dict:
    d = db.get(Document, doc_id)
    if not d:
        return {"ok": False}
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.get("/admin/sources")
def admin_sources(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> list[dict]:
    rows = db.query(Source).order_by(Source.priority.asc(), Source.id.desc()).all()
    return [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "url": s.url,
            "type": s.type,
            "category": s.category,
            "priority": s.priority,
            "active": s.active,
            "last_crawled_at": s.last_crawled_at.isoformat()
            if s.last_crawled_at
            else None,
            "documents": db.query(Document).filter_by(source_id=s.id).count(),
        }
        for s in rows
    ]


class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    url: str = Field(min_length=8)
    type: str = "portal"
    category: str = "manual"
    priority: str = "P1"
    active: bool = True


@router.post("/admin/sources")
def admin_create_source(
    body: SourceIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> dict:
    from backend.crawler.ingest import ensure_source

    src = ensure_source(
        db,
        url=body.url.strip(),
        name=body.name.strip(),
        category=body.category,
        priority=body.priority,
        type_=body.type,
    )
    src.active = body.active
    src.name = body.name.strip()
    db.commit()
    return {"ok": True, "id": src.id, "code": src.code, "url": src.url}


class IngestUrlIn(BaseModel):
    url: str = Field(min_length=8)
    title: str | None = None
    source_name: str | None = None
    category: str = "manual"


class IngestTextIn(BaseModel):
    title: str = Field(min_length=2, max_length=512)
    text: str = Field(min_length=40)
    url: str | None = None
    source_name: str | None = None
    category: str = "manual"


@router.post("/admin/ingest/url")
def admin_ingest_url(
    body: IngestUrlIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> dict:
    from backend.crawler.fetcher import Fetcher
    from backend.crawler.html_parser import extract_html
    from backend.crawler.ingest import ensure_source, ingest_text_document, mark_source_crawled
    from backend.crawler.office import extract_doc_legacy, extract_docx, extract_xlsx
    from backend.crawler.pdf import extract_pdf

    raw_url = body.url.strip()
    fetched = Fetcher().fetch(raw_url)
    if not fetched or fetched.status >= 400:
        raise HTTPException(400, f"Nu am putut descărca URL-ul (status={getattr(fetched, 'status', None)})")

    ctype = fetched.content_type or ""
    title = (body.title or "").strip()
    text = ""
    pages: list[str] | None = None
    mime = ctype or "text/plain"

    if "pdf" in ctype or raw_url.lower().endswith(".pdf"):
        text, pages = extract_pdf(fetched.body)
        mime = "application/pdf"
        title = title or urlparse(fetched.final_url).path.split("/")[-1] or "PDF"
    elif "html" in ctype or ctype in ("", "application/octet-stream"):
        try:
            title_h, text, _links = extract_html(fetched.final_url, fetched.body)
            title = title or title_h or fetched.final_url
            mime = "text/html"
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"HTML parse failed: {exc}") from exc
    elif "word" in ctype or raw_url.lower().endswith(".docx"):
        text = extract_docx(fetched.body)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        title = title or "Document DOCX"
    elif "sheet" in ctype or raw_url.lower().endswith(".xlsx"):
        text = extract_xlsx(fetched.body)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        title = title or "Spreadsheet"
    elif raw_url.lower().endswith(".doc"):
        text = extract_doc_legacy(fetched.body)
        mime = "application/msword"
        title = title or "Document DOC"
    else:
        try:
            text = fetched.body.decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Unsupported content-type: {ctype}") from exc

    if len((text or "").strip()) < 40:
        raise HTTPException(400, "Conținut prea scurt după extragere (<40 caractere)")

    src = ensure_source(
        db,
        url=fetched.final_url,
        name=body.source_name or urlparse(fetched.final_url).netloc,
        category=body.category,
        priority="P1",
        type_="manual",
    )
    doc = ingest_text_document(
        db,
        source=src,
        title=title[:512],
        url=fetched.final_url,
        text=text,
        mime_type=mime,
        pages=pages,
    )
    mark_source_crawled(db, src)
    db.commit()
    if not doc:
        raise HTTPException(400, "Ingest eșuat")
    chunks = db.query(Chunk).filter_by(document_id=doc.id).count()
    return {
        "ok": True,
        "document_id": doc.id,
        "title": doc.title,
        "url": doc.url,
        "chunks": chunks,
        "source_id": src.id,
    }


@router.post("/admin/ingest/text")
def admin_ingest_text(
    body: IngestTextIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
) -> dict:
    from backend.crawler.ingest import ensure_source, ingest_text_document, mark_source_crawled

    fake_url = (body.url or "").strip() or f"manual://admin/{body.title.strip()[:80]}"
    src = ensure_source(
        db,
        url=fake_url if fake_url.startswith("http") else "https://civic.ai/manual",
        name=body.source_name or "Materiale admin",
        category=body.category,
        priority="P1",
        type_="manual",
    )
    doc = ingest_text_document(
        db,
        source=src,
        title=body.title.strip(),
        url=fake_url,
        text=body.text,
        mime_type="text/plain",
    )
    mark_source_crawled(db, src)
    db.commit()
    if not doc:
        raise HTTPException(400, "Ingest eșuat")
    chunks = db.query(Chunk).filter_by(document_id=doc.id).count()
    return {
        "ok": True,
        "document_id": doc.id,
        "title": doc.title,
        "url": doc.url,
        "chunks": chunks,
        "source_id": src.id,
    }


class CostProjectIn(BaseModel):
    active_users: int = Field(default=200, ge=1, le=1_000_000)
    requests_per_user_month: float = Field(default=28.0, ge=0.1, le=10_000)
    avg_input_tokens: int = Field(default=1400, ge=50, le=100_000)
    avg_output_tokens: int = Field(default=420, ge=20, le=32_000)
    tool_calls_per_q: float = Field(default=1.3, ge=0, le=20)
    llm_provider: str = "groq_gpt_oss_120b"
    embedding_provider: str = "local_bge_m3"
    rerank_provider: str = "local_bge"
    infra_fixed_usd: float = Field(default=55.0, ge=0)
    electricity_usd: float = Field(default=28.0, ge=0)
    storage_usd: float = Field(default=12.0, ge=0)
    bandwidth_usd: float = Field(default=14.0, ge=0)
    support_hours: float = Field(default=16.0, ge=0)
    support_hourly_usd: float = Field(default=15.0, ge=0)
    target_profit_usd: float = Field(default=450.0, ge=0)
    margin_pct: float | None = Field(default=30.0, ge=0, le=95)
    fx_mdl: float = Field(default=17.85, ge=1)


@router.get("/admin/cost")
def admin_cost(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> dict:
    """Legacy + catalog snapshot; use POST /admin/cost/project for full projections."""
    from backend.ai.pricing import DEFAULT_OPEX, catalog, project_costs

    docs = db.query(Document).count()
    chunks = db.query(Chunk).count()
    searches = db.query(SearchLog).count()
    users_n = max(
        1,
        db.query(User)
        .filter((User.approved.is_(True)) | (User.role.in_(["admin", "manager"])))
        .count(),
    )
    base = project_costs(
        active_users=max(users_n, int(DEFAULT_OPEX["active_users"])),
        requests_per_user_month=float(DEFAULT_OPEX["requests_per_user_month"]),
        chunks_indexed=chunks,
        llm_provider="groq_gpt_oss_120b",
        target_profit_usd=float(DEFAULT_OPEX["target_profit_usd"]),
        margin_pct=float(DEFAULT_OPEX["margin_pct"]),
    )
    return {
        **base,
        "catalog": catalog(),
        "corpus": {
            "documents": docs,
            "chunks": chunks,
            "searches_logged": searches,
            "approved_users": users_n,
            "target_documents": 5000,
            "progress_pct": min(100, round(100 * docs / 5000, 1)),
        },
    }


@router.post("/admin/cost/project")
def admin_cost_project(
    body: CostProjectIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    from backend.ai.pricing import catalog, project_costs

    chunks = db.query(Chunk).count()
    result = project_costs(
        active_users=body.active_users,
        requests_per_user_month=body.requests_per_user_month,
        avg_input_tokens=body.avg_input_tokens,
        avg_output_tokens=body.avg_output_tokens,
        tool_calls_per_q=body.tool_calls_per_q,
        llm_provider=body.llm_provider,
        embedding_provider=body.embedding_provider,
        rerank_provider=body.rerank_provider,
        chunks_indexed=chunks,
        infra_fixed_usd=body.infra_fixed_usd,
        electricity_usd=body.electricity_usd,
        storage_usd=body.storage_usd,
        bandwidth_usd=body.bandwidth_usd,
        support_hours=body.support_hours,
        support_hourly_usd=body.support_hourly_usd,
        target_profit_usd=body.target_profit_usd,
        margin_pct=body.margin_pct,
        fx_mdl=body.fx_mdl,
    )
    result["catalog"] = catalog()
    result["corpus_chunks"] = chunks
    return result


@router.get("/admin/cost/catalog")
def admin_cost_catalog(_: User = Depends(require_admin)) -> dict:
    from backend.ai.pricing import catalog

    return catalog()


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
