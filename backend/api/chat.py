from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.ai.answer_status import answer_claims_missing
from backend.ai.analyze import is_job_question, offtopic_reply, wants_current
from backend.ai.current_jobs import job_evidence_excerpt, sector_in_question
from backend.ai.conflicts import detect_document_conflicts
from backend.ai.conversation_cache import find_prior_answer
from backend.ai.followups import contextualize_question
from backend.ai.llm import get_llm_service
from backend.ai.retrieval import HybridRetriever, RetrievedChunk
from backend.ai.verifier import (
    is_generic_assistant_blurb,
    question_about_deadline,
    verify_evidence,
)
from backend.api.auth import User, require_approved
from backend.db.database import get_db
from backend.db.models import TopicLink

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k: int = Field(12, ge=1, le=30)
    session_id: int | None = None
    ui_language: str | None = Field(
        default=None,
        description="UI language preference: ro | ru | en (soft hint for answer language)",
    )


class SourceOut(BaseModel):
    document: str
    page: int | None = None
    section: str | None = None
    quote: str
    url: str | None = None
    source_type: str | None = None
    year: int | None = None


class NextAction(BaseModel):
    label: str
    url: str
    contact: str | None = None


class ConflictSide(BaseModel):
    document: str
    days: list[int] = Field(default_factory=list)
    value: str = ""
    quote: str = ""
    url: str | None = None
    page: str | None = None


class ConflictPair(BaseModel):
    field: str = "duration_days"
    left: ConflictSide
    right: ConflictSide


class ChatResponse(BaseModel):
    status: str
    answer: str
    sources: list[SourceOut] = Field(default_factory=list)
    next_action: NextAction | None = None
    confidence: str = "medium"
    confidence_score: float = 0.5
    language: str = "ro"
    evidence_preview: list[SourceOut] = Field(default_factory=list)
    session_id: int | None = None
    conflicts: list[ConflictPair] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    corpus: dict | None = None


def _is_ru(q: str) -> bool:
    return any("\u0400" <= c <= "\u04FF" for c in q)


def _missing_answer(lang: str, question: str = "", *, no_results: bool = False) -> str:
    if is_job_question(question) and wants_current(question):
        sector = sector_in_question(question)
        where = f" în sectorul {sector.capitalize()}" if sector else ""
        if lang == "ru":
            return "В доступных документах не удалось подтвердить конкурс с ещё открытым сроком подачи заявок."
        if lang == "en":
            return "I could not verify a job announcement with an application deadline still open in the indexed documents."
        return (
            f"Nu am putut verifica în documentele indexate concursuri{where} "
            "cu termen de depunere încă deschis."
        )
    if lang == "ru":
        if no_results:
            return "По этому вопросу не найдено подходящих документов в проиндексированном корпусе."
        return "Найденные документы не подтверждают ответ на этот вопрос."
    if lang == "en":
        if no_results:
            return "No relevant documents were retrieved from the indexed corpus for this question."
        return "The retrieved documents do not verify an answer to this question."
    if no_results:
        return "Nu am găsit documente relevante în corpusul indexat pentru această întrebare."
    return "Documentele găsite nu confirmă un răspuns la această întrebare."


def _conflict_response(conflicts: list[dict], lang: str) -> ChatResponse:
    """State the documented values without asking the model to resolve them."""
    pair = ConflictPair.model_validate(conflicts[0])
    left, right = pair.left, pair.right

    def display_value(side: ConflictSide) -> str:
        if pair.field == "duration_days" and side.days:
            unit = "days" if lang == "en" else "дней" if lang == "ru" else "zile"
            return f"{side.days[0]} {unit}"
        return side.value

    left_value, right_value = display_value(left), display_value(right)
    if lang == "ru":
        answer = (
            f"В документах обнаружено возможное расхождение по запрошенной услуге: "
            f"{left_value} [1] и {right_value} [2]. Проверьте оба источника перед подачей заявления."
        )
    elif lang == "en":
        answer = (
            f"The documents show a possible discrepancy for the requested service: "
            f"{left_value} [1] and {right_value} [2]. Check both sources before applying."
        )
    else:
        answer = (
            f"Documentele indică o posibilă neconcordanță pentru serviciul cerut: "
            f"{left_value} [1] și {right_value} [2]. Verificați ambele surse înainte de depunerea cererii."
        )

    def source(side: ConflictSide) -> SourceOut:
        return SourceOut(
            document=side.document,
            page=int(side.page) if side.page and side.page.isdigit() else None,
            quote=side.quote,
            url=side.url,
        )

    sources = [source(left), source(right)]
    return ChatResponse(
        status="conflict",
        answer=answer,
        sources=sources,
        confidence="low",
        confidence_score=0.4,
        language=lang,
        evidence_preview=sources,
        conflicts=[ConflictPair.model_validate(c) for c in conflicts],
    )


def _evidence_blocks(chunks: list[RetrievedChunk], *, question: str = "") -> list[str]:
    from backend.crawler.html_parser import scrub_indexed_text

    blocks = []
    for i, c in enumerate(chunks, 1):
        text = re.sub(
            r"\[expire_date\]|\[featured_image\]|Download is available until[^\n]*",
            "",
            c.content or "",
            flags=re.IGNORECASE,
        )
        text = scrub_indexed_text(text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if is_job_question(question):
            text = job_evidence_excerpt(text)
        if len(text) < 40:
            # fall back to title so we still have a topical hook
            text = (c.document_title or "").strip()
        blocks.append(
            f"[{i}] document={c.document_title}\n"
            f"page={c.page} section={c.section}\n"
            f"url={c.document_url}\n"
            f"text={text[:2200]}"
        )
    return blocks


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chunk_to_source(h: RetrievedChunk) -> SourceOut:
    from backend.ai.tools import classify_doc_type
    from backend.ai.verifier import _chunk_year

    return SourceOut(
        document=h.document_title,
        page=h.page,
        section=h.section,
        quote=(h.content or "")[:400],
        url=h.document_url,
        source_type=classify_doc_type(
            h.document_title or "", h.document_url, h.content or ""
        ),
        year=_chunk_year(h),
    )


def _parse_refs(answer: str, n_evidence: int) -> list[int]:
    refs = []
    for m in re.finditer(r"\[(\d+)\]", answer or ""):
        i = int(m.group(1))
        if 1 <= i <= n_evidence and i not in refs:
            refs.append(i)
    return refs


_PLACEHOLDER_RE = re.compile(
    r"(?:"
    r"\[expire_date\]|\[featured_image\]|\[n\]|§LINK§[^§]*§?|"
    r"Disponibil[ăa]\s+pân[aă]\s+la\s*\[?[^\]\n]*\]?|"
    r"Download is available until[^\n]*"
    r")",
    re.IGNORECASE,
)


def _sanitize_answer(answer: str) -> str:
    text = answer or ""
    text = _PLACEHOLDER_RE.sub("", text)
    text = re.sub(r"https?://[^\s)>\]]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ground_sources(
    usable: list[RetrievedChunk],
    refs: list[int] | None,
    *,
    status: str,
    question: str = "",
) -> list[SourceOut]:
    if status == "missing" or not usable:
        return []

    from backend.ai.verifier import _token_overlap

    def unique(items: list[SourceOut]) -> list[SourceOut]:
        seen: set[str] = set()
        out: list[SourceOut] = []
        for s in items:
            key = (s.url or "") + "|" + (s.document or "") + "|" + str(s.page)
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    ranked = list(usable)
    if question:
        ranked = sorted(
            usable,
            key=lambda c: _token_overlap(
                question, f"{c.document_title or ''} {c.content or ''}"
            ),
            reverse=True,
        )

    if refs:
        out = []
        for i in refs:
            if 1 <= i <= len(usable):
                out.append(_chunk_to_source(usable[i - 1]))
        out = unique(out)
        if out and question and ranked:
            best = _chunk_to_source(ranked[0])
            if best.url and all(best.url != s.url for s in out):
                best_ov = _token_overlap(
                    question, f"{ranked[0].document_title} {ranked[0].content}"
                )
                cited = usable[refs[0] - 1] if refs[0] <= len(usable) else None
                cited_ov = (
                    _token_overlap(
                        question, f"{cited.document_title} {cited.content}"
                    )
                    if cited
                    else 0
                )
                if best_ov > cited_ov + 0.15:
                    out = unique([best] + out)
            return out[:4]
        if out:
            return out[:4]
    return unique([_chunk_to_source(h) for h in ranked[:10]])[:8]


def _pick_next_action(
    question: str,
    links: list[TopicLink],
    evidence_urls: list[str],
) -> NextAction | None:
    """Prefer topic match or first evidence URL — never force homepage blindly."""
    q = (question or "").lower()
    best: TopicLink | None = None
    best_score = 0
    for t in links:
        score = 0
        for part in re.split(r"[\s/,_-]+", (t.topic_ro or "").lower()):
            if len(part) >= 4 and part in q:
                score += 2
        for part in re.split(r"[\s/,_-]+", (t.topic_ru or "").lower()):
            if len(part) >= 4 and part in q:
                score += 2
        if t.url and t.url.rstrip("/") in evidence_urls:
            score += 3
        if score > best_score:
            best_score = score
            best = t
    if best and best_score > 0:
        return NextAction(
            label=best.contact_label or best.topic_ro,
            url=best.url,
            contact=best.contact_value,
        )
    # exact evidence document link
    for u in evidence_urls:
        if u and u.rstrip("/") not in {"http://chisinau.md", "https://chisinau.md", "https://www.chisinau.md"}:
            return NextAction(label="Deschide sursa", url=u, contact=None)
    return None


def _persist_turn(
    db: Session,
    user: User | None,
    session_id: int | None,
    question: str,
    result: ChatResponse,
) -> int | None:
    if not user:
        return session_id
    from backend.api.chats import ensure_session, add_message

    sid = ensure_session(db, user.id, session_id, title=question[:80])
    add_message(db, sid, "user", question)
    add_message(
        db,
        sid,
        "assistant",
        result.answer,
        status=result.status,
        sources=[s.model_dump() for s in result.sources],
        conflicts=[c.model_dump() for c in result.conflicts],
        next_action=result.next_action.model_dump() if result.next_action else None,
    )
    return sid


def _answer_from_history(
    db: Session, user: User, body: ChatRequest
) -> ChatResponse | None:
    """Reuse a recent sourced answer from a session owned by this user."""
    if not body.session_id:
        return None
    from backend.api.chats import ChatMessage, ChatSession

    session = db.get(ChatSession, body.session_id)
    if session is None or session.user_id != user.id:
        return None
    messages = (
        db.query(ChatMessage)
        .filter_by(session_id=session.id)
        .order_by(ChatMessage.id.desc())
        .limit(200)
        .all()
    )
    prior = find_prior_answer(list(reversed(messages)), body.question)
    if prior is None:
        return None
    try:
        sources = [SourceOut.model_validate(s) for s in json.loads(prior.sources_json)]
        if not any(s.url for s in sources) or answer_claims_missing(prior.content):
            return None
        next_action = (
            NextAction.model_validate(json.loads(prior.next_action_json))
            if prior.next_action_json
            else None
        )
    except (ValueError, TypeError):
        return None
    return ChatResponse(
        status="reused",
        answer=prior.content,
        sources=sources,
        next_action=next_action,
        confidence="medium",
        confidence_score=0.5,
        language="ru" if _is_ru(body.question) else "ro",
        evidence_preview=sources,
        tools_used=["conversation_history"],
    )


def _question_for_search(db: Session, user: User, body: ChatRequest) -> str:
    """Read one prior user turn only from a session owned by this user."""
    if not body.session_id:
        return body.question
    from backend.api.chats import ChatMessage, ChatSession

    session = db.get(ChatSession, body.session_id)
    if session is None or session.user_id != user.id:
        return body.question
    previous = (
        db.query(ChatMessage)
        .filter_by(session_id=session.id, role="user")
        .order_by(ChatMessage.id.desc())
        .first()
    )
    return contextualize_question(body.question, previous.content if previous else None)


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_approved),
) -> ChatResponse:
    try:
        cached = _answer_from_history(db, user, body)
        if cached is not None:
            cached.session_id = _persist_turn(
                db, user, body.session_id, body.question, cached
            )
            return cached
        search_body = body.model_copy(
            update={"question": _question_for_search(db, user, body)}
        )
        result = _build_response(body=search_body, db=db)
        sid = _persist_turn(db, user, body.session_id, body.question, result)
        result.session_id = sid
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat failed")
        return ChatResponse(
            status="missing",
            answer=f"Eroare internă la generare: {exc}",
            sources=[],
            confidence="low",
            language="ro",
        )


def _build_response(*, body: ChatRequest, db: Session) -> ChatResponse:
    lang = "ru" if _is_ru(body.question) else "ro"
    links = db.query(TopicLink).all()

    from backend.ai.analyze import analyze_question_meta
    from backend.ai.scope import classify_scope

    meta = analyze_question_meta(body.question, ui_language=body.ui_language)
    lang = meta["language"]
    scope = classify_scope(body.question, language=lang)
    if not scope["relevant"]:
        return ChatResponse(
            status="out_of_scope",
            answer=scope["reply"] or offtopic_reply(lang),
            sources=[],
            next_action=None,
            confidence="high",
            confidence_score=0.9,
            language=lang,
        )
    retriever = HybridRetriever(db)
    hits = retriever.search(body.question, top_k=body.top_k)
    gate, usable = verify_evidence(
        hits,
        question=body.question,
        answer_mode=meta.get("answer_mode") or "fact",
        wants_list=bool(meta.get("wants_list")),
    )
    preview = [_chunk_to_source(h) for h in usable] if gate != "missing" else []
    evidence_urls = [h.document_url for h in usable if h.document_url]

    if gate == "missing":
        return ChatResponse(
            status="missing",
            answer=_missing_answer(lang, body.question, no_results=not hits),
            sources=[],
            next_action=None,
            confidence="low",
            confidence_score=0.2,
            language=lang,
            evidence_preview=[],
        )

    conflicts = detect_document_conflicts(usable, body.question)
    if conflicts:
        return _conflict_response(conflicts, lang)

    link_lines = [
        f"- {t.topic_ro} / {t.topic_ru} → {t.url} ({t.contact_label}: {t.contact_value})"
        for t in links
    ]
    raw = get_llm_service().generate_structured(
        body.question,
        _evidence_blocks(usable, question=body.question),
        link_lines,
    )
    answer = raw.get("answer") or ""
    refs = raw.get("refs") if isinstance(raw.get("refs"), list) else []
    refs = [int(x) for x in refs if str(x).isdigit()]
    if not refs:
        refs = _parse_refs(answer, len(usable))

    status_val = gate
    # LLM may say missing — trust if evidence weak
    if raw.get("status") == "missing":
        status_val = "missing"
        answer = _missing_answer(lang, body.question)
        refs = []

    if gate == "conflict" and question_about_deadline(body.question):
        status_val = "conflict"
        joined = " ".join(c.content for c in usable)
        if "30" in joined and "20" in joined and "⚠" not in answer:
            answer = (
                "⚠️ Documentele disponibile conțin informații contradictorii privind termenul.\n\n"
                + answer
            )
    elif gate == "conflict":
        status_val = "supported"

    if (
        is_generic_assistant_blurb(answer)
        or answer_claims_missing(answer)
        or status_val == "missing"
    ):
        status_val = "missing"
        answer = _missing_answer(lang, body.question)
        refs = []

    if status_val == "missing":
        return ChatResponse(
            status="missing",
            answer=answer,
            sources=[],
            next_action=None,
            confidence="low",
            confidence_score=0.2,
            language=raw.get("language") or lang,
            evidence_preview=[],
        )
    sources = _ground_sources(
        usable, refs, status=status_val, question=body.question
    )
    return ChatResponse(
        status=status_val,
        answer=_sanitize_answer(answer),
        sources=sources,
        next_action=_pick_next_action(
            body.question, links, [s.url for s in sources if s.url] or evidence_urls
        ),
        confidence=raw.get("confidence") or "medium",
        language=raw.get("language") or lang,
        evidence_preview=preview,
    )


@router.post("/chat/stream")
def chat_stream(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_approved),
) -> StreamingResponse:
    def event_gen() -> Iterator[str]:
        import time as _time

        from backend.ai.tools import AgentState, ToolEvent, run_agent_pipeline

        t0 = _time.perf_counter()
        try:
            cached = _answer_from_history(db, user, body)
            if cached is not None:
                cached.latency_ms = int((_time.perf_counter() - t0) * 1000)
                yield _sse("token", {"t": cached.answer})
                cached.session_id = _persist_turn(
                    db, user, body.session_id, body.question, cached
                )
                yield _sse("result", cached.model_dump())
                yield _sse("done", {})
                return
            search_question = _question_for_search(db, user, body)
            lang = "ru" if _is_ru(search_question) else "ro"

            state: AgentState | None = None
            for item in run_agent_pipeline(
                db,
                search_question,
                top_k=body.top_k,
                ui_language=body.ui_language,
            ):
                if isinstance(item, ToolEvent):
                    yield _sse(
                        "tool",
                        {
                            "name": item.name,
                            "status": item.status,
                            "label_ro": item.label_ro,
                            "label_ru": item.label_ru,
                            "label_en": item.label_en or item.label_ro,
                            "detail": item.detail,
                            "ms": item.ms,
                            "optional": item.optional,
                            "data": {
                                k: v
                                for k, v in (item.data or {}).items()
                                if k
                                not in (
                                    "hits",
                                    "usable",
                                    "text",
                                )
                                and not hasattr(v, "document_id")
                            },
                        },
                    )
                    # also mirror as status for older clients
                    if item.status == "start":
                        yield _sse(
                            "status",
                            {
                                "step": item.name,
                                "label_ro": item.label_ro + "…",
                                "label_ru": item.label_ru + "…",
                                "label_en": (item.label_en or item.label_ro) + "…",
                            },
                        )
                elif isinstance(item, AgentState):
                    state = item

            if state is None:
                raise RuntimeError("agent pipeline returned no state")

            lang = state.language or lang
            usable = state.usable
            gate = state.gate
            evidence_urls = [h.document_url for h in usable if h.document_url]

            na = None
            if state.contact:
                na = NextAction(
                    label=state.contact.get("label") or "Contact",
                    url=state.contact.get("url") or "https://www.chisinau.md/",
                    contact=state.contact.get("contact"),
                )

            if state.conflicts:
                cr = _conflict_response(state.conflicts, lang)
                cr.tools_used = list(state.tools_run)
                cr.latency_ms = int((_time.perf_counter() - t0) * 1000)
                yield _sse("token", {"t": cr.answer})
                cr.session_id = _persist_turn(
                    db, user, body.session_id, body.question, cr
                )
                yield _sse("result", cr.model_dump())
                yield _sse("done", {})
                return

            if gate == "missing" and not state.fetched:
                answer = (
                    state.contact_answer
                    if (state.scope_rejected and state.contact_answer)
                    else _missing_answer(
                        lang, search_question, no_results=not state.hits and not state.fetched
                    )
                )
                display_status = "out_of_scope" if state.scope_rejected else "missing"
                result = {
                    "status": display_status,
                    "answer": answer,
                    "sources": [],
                    "next_action": na.model_dump() if na else None,
                    "confidence": state.confidence or "high",
                    "confidence_score": state.confidence_score
                    or (0.9 if state.scope_rejected else 0.2),
                    "language": lang,
                    "evidence_preview": [],
                    "conflicts": [],
                    "tools_used": state.tools_run,
                    "corpus": state.health,
                    "latency_ms": int((_time.perf_counter() - t0) * 1000),
                }
                cr = ChatResponse(
                    status=display_status,
                    answer=result["answer"],
                    sources=[],
                    next_action=na,
                    confidence=result["confidence"],
                    confidence_score=result["confidence_score"],
                    language=lang,
                    tools_used=state.tools_run,
                    latency_ms=result["latency_ms"],
                    corpus=state.health,
                )
                result["session_id"] = _persist_turn(
                    db, user, body.session_id, body.question, cr
                )
                yield _sse("result", result)
                yield _sse("done", {})
                return

            # Fast path: curated contact answer (no LLM hallucination)
            if state.contact_answer and state.known_contact:
                yield _sse(
                    "tool",
                    {
                        "name": "generate_answer",
                        "status": "start",
                        "label_ro": "Generez răspunsul",
                        "label_en": "Generating the answer",
                        "label_ru": "Генерирую ответ",
                        "detail": "",
                        "ms": 0,
                    },
                )
                answer = state.contact_answer
                yield _sse("token", {"t": answer})
                yield _sse(
                    "tool",
                    {
                        "name": "generate_answer",
                        "status": "done",
                        "label_ro": "Generez răspunsul",
                        "label_en": "Generating the answer",
                        "label_ru": "Генерирую ответ",
                        "detail": "contact lookup",
                        "ms": 0,
                    },
                )
                kc = state.known_contact
                sources_models = [
                    SourceOut(
                        document=kc.get("name") or "Contact oficial",
                        page=None,
                        section="Contact",
                        quote=(
                            f"{kc.get('address', '')}; tel. {kc.get('phone', '')}; "
                            f"{kc.get('email', '')}"
                        )[:280],
                        url=kc.get("url"),
                        source_type="contact",
                        year=None,
                    )
                ]
                # Prefer corpus hit if present
                for h in usable:
                    title = (h.document_title or "").lower()
                    if "contact" in title or (
                        state.institution and state.institution in title
                    ):
                        sources_models = [_chunk_to_source(h)]
                        sources_models[0].source_type = "contact"
                        break
                status_val = "supported"
                latency = int((_time.perf_counter() - t0) * 1000)
                tools_used = list(state.tools_run) + ["generate_answer"]
                sources = [s.model_dump() for s in sources_models]
                result = {
                    "status": status_val,
                    "answer": answer,
                    "sources": sources,
                    "next_action": na.model_dump() if na else None,
                    "confidence": state.confidence,
                    "confidence_score": state.confidence_score,
                    "language": lang,
                    "evidence_preview": sources,
                    "conflicts": [],
                    "tools_used": tools_used,
                    "corpus": state.health,
                    "latency_ms": latency,
                }
                cr = ChatResponse(
                    status=status_val,
                    answer=answer,
                    sources=sources_models,
                    next_action=na,
                    confidence=state.confidence,
                    confidence_score=state.confidence_score,
                    language=lang,
                    tools_used=tools_used,
                    latency_ms=latency,
                    corpus=state.health,
                )
                result["session_id"] = _persist_turn(
                    db, user, body.session_id, body.question, cr
                )
                yield _sse("result", result)
                yield _sse("done", {})
                return

            yield _sse(
                "status",
                {
                    "step": "generate",
                    "label_ro": "Generez răspunsul…",
                    "label_en": "Generating the answer...",
                    "label_ru": "Генерирую ответ…",
                },
            )
            yield _sse(
                "tool",
                {
                    "name": "generate_answer",
                    "status": "start",
                    "label_ro": "Generez răspunsul",
                    "label_en": "Generating the answer",
                    "label_ru": "Генерирую ответ",
                    "detail": "",
                    "ms": 0,
                },
            )

            evidence = _evidence_blocks(usable, question=search_question)
            if state.fetched:
                for i, f in enumerate(state.fetched, 1):
                    evidence.append(
                        f"[URL:{i}] document={f.get('title')}\n"
                        f"url={f.get('url')}\n"
                        f"text={(f.get('text') or '')[:900]}"
                    )
            if state.known_contact:
                kc = state.known_contact
                evidence.insert(
                    0,
                    "[CONTACT:0] document=Contact oficial verificat\n"
                    f"url={kc.get('url')}\n"
                    f"text={kc.get('name')}; {kc.get('address')}; "
                    f"tel. {kc.get('phone')}; email {kc.get('email')}",
                )

            answer_parts: list[str] = []
            t_gen = _time.perf_counter()
            for token in get_llm_service().stream_answer(
                search_question,
                evidence,
                language_meta=state.language_meta
                or {
                    "answer_language": lang,
                    "question_language": lang,
                    "ui_language": body.ui_language,
                    "question_confidence": 0.5,
                },
            ):
                answer_parts.append(token)
                yield _sse("token", {"t": token})
            gen_ms = int((_time.perf_counter() - t_gen) * 1000)
            yield _sse(
                "tool",
                {
                    "name": "generate_answer",
                    "status": "done",
                    "label_ro": "Generez răspunsul",
                    "label_ru": "Генерирую ответ",
                    "detail": f"{gen_ms} ms",
                    "ms": gen_ms,
                },
            )

            answer = _sanitize_answer("".join(answer_parts).strip())
            refs = _parse_refs(answer, len(usable))
            status_val = gate if gate in ("supported", "conflict", "missing") else "supported"
            if state.conflicts:
                status_val = "conflict"
                if "⚠" not in answer and "contradic" not in answer.lower():
                    answer = (
                        "⚠️ Documentele disponibile conțin informații contradictorii "
                        "privind termenul.\n\n"
                        + answer
                    )
            if is_generic_assistant_blurb(answer):
                status_val = "missing"
                answer = _missing_answer(
                    lang, search_question, no_results=not state.hits and not state.fetched
                )
                refs = []
            # Model denied corpus coverage → treat as missing, no anexas / CTA
            if status_val != "conflict" and (
                status_val == "missing" or answer_claims_missing(answer)
            ):
                status_val = "missing"
                answer = _missing_answer(
                    lang, search_question, no_results=not state.hits and not state.fetched
                )
                refs = []
                usable = []
                na = None
                state.confidence = "low"
                state.confidence_score = 0.2

            sources_models = _ground_sources(
                usable, refs, status=status_val, question=search_question
            )
            # enrich types from state.source_meta
            type_by_url = {
                (m.get("url") or ""): m.get("type") for m in state.source_meta
            }
            for s in sources_models:
                if s.url and type_by_url.get(s.url):
                    s.source_type = type_by_url[s.url]

            sources = [s.model_dump() for s in sources_models]
            conflicts_out = state.conflicts or []
            latency = int((_time.perf_counter() - t0) * 1000)
            tools_used = list(state.tools_run) + ["generate_answer"]
            preview = (
                []
                if status_val == "missing"
                else [_chunk_to_source(h).model_dump() for h in usable]
            )

            result = {
                "status": status_val,
                "answer": answer,
                "sources": sources,
                "next_action": na.model_dump() if na else None,
                "confidence": state.confidence if status_val != "missing" else "low",
                "confidence_score": (
                    state.confidence_score if status_val != "missing" else 0.2
                ),
                "language": lang,
                "evidence_preview": preview,
                "conflicts": conflicts_out if status_val != "missing" else [],
                "tools_used": tools_used,
                "corpus": state.health,
                "latency_ms": latency,
            }
            cr = ChatResponse(
                status=status_val,
                answer=answer,
                sources=sources_models,
                next_action=na if status_val != "missing" else None,
                confidence="low" if status_val == "missing" else state.confidence,
                confidence_score=(
                    0.2 if status_val == "missing" else state.confidence_score
                ),
                language=lang,
                conflicts=[
                    ConflictPair.model_validate(c) for c in conflicts_out
                ]
                if status_val != "missing"
                else [],
                tools_used=tools_used,
                latency_ms=latency,
                corpus=state.health,
            )
            result["session_id"] = _persist_turn(
                db, user, body.session_id, body.question, cr
            )
            yield _sse("result", result)
            yield _sse("done", {})
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream chat failed")
            yield _sse(
                "result",
                {
                    "status": "missing",
                    "answer": (
                        "Nu am putut finaliza răspunsul acum. "
                        "Te rugăm să încerci din nou."
                    ),
                    "sources": [],
                    "next_action": None,
                    "confidence": "low",
                    "confidence_score": 0.1,
                    "language": "ro",
                    "evidence_preview": [],
                    "conflicts": [],
                    "tools_used": [],
                    "error": str(exc)[:160],
                },
            )
            yield _sse("done", {})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
