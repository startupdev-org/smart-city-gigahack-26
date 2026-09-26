from __future__ import annotations

import re
from collections import defaultdict

from backend.ai.analyze import (
    fold,
    is_job_question,
    overlap_score,
    wants_current as analyze_wants_current,
    wants_list as analyze_wants_list,
)
from backend.ai.retrieval import RetrievedChunk

_DAY_RE = re.compile(
    r"(\d{1,3})\s*(?:de\s+)?(?:zile|дней|дня|zi|день)\s*(?:lucrătoare|рабочих|calendaristice|календарных)?",
    re.IGNORECASE,
)

_TERM_Q_RE = re.compile(
    r"\b(termen|deadline|срочн|срок|cât\s+durează|cat\s+dureaza|zile\s+lucr|"
    r"în\s+cât\s+timp|in\s+cat\s+timp)\b",
    re.IGNORECASE,
)

_OFFTOPIC_RE = re.compile(
    r"(?:"
    r"cine\s+sunt\s+eu|who\s+am\s+i|как\s+меня\s+зовут|кто\s+я"
    r"|ce\s+(?:mi-ai|ti-am|ți-am|ti\s+am)\s+(?:scris|spus|zise)"
    r"|what\s+did\s+i\s+(?:say|write)|previous\s+message|istoric(ul)?\s+chat"
    r"|îți\s+amintești|iti\s+amintesti|remember\s+what"
    r"|spune[- ]mi\s+o\s+glumă|tell\s+me\s+a\s+joke"
    r"|cum\s+te\s+cheamă|what\s+is\s+your\s+name"
    r")",
    re.IGNORECASE,
)

_GENERIC_ASSISTANT_RE = re.compile(
    r"(?:"
    r"sunt\s+un\s+asistent"
    r"|I\s+am\s+(?:an?\s+)?(?:AI\s+)?assistant"
    r"|pot\s+oferi\s+informații\s+despre\s+serviciile\s+publice"
    r"|для\s+того\s+чтобы\s+предоставить\s+точную"
    r"|vă\s+rog\s+să[- ]mi\s+specificați\s+ce\s+doriți"
    r")",
    re.IGNORECASE,
)


def is_offtopic_question(question: str) -> bool:
    from backend.ai.analyze import looks_clearly_offtopic, looks_municipal

    if looks_municipal(question):
        return False
    return bool(_OFFTOPIC_RE.search(question or "")) or looks_clearly_offtopic(
        question
    )


def question_about_deadline(question: str) -> bool:
    return bool(_TERM_Q_RE.search(question or ""))


def is_generic_assistant_blurb(answer: str) -> bool:
    return bool(_GENERIC_ASSISTANT_RE.search(answer or ""))


def _deadline_mentions(text: str) -> set[int]:
    return {int(m.group(1)) for m in _DAY_RE.finditer(text or "")}


def _token_overlap(question: str, text: str) -> float:
    """Backward-compatible wrapper — diacritic-tolerant."""
    return overlap_score(question, text)


_YEAR_RE = re.compile(r"(?:/|[^0-9])(20\d{2})(?:/|[^0-9])")
_CURRENTISH_Q = re.compile(
    r"\b(acum|current|now|deschis|открыт|vacant[ăaе]?|конкурс|funcți[ei].*vacant|"
    r"angajar|job|astăzi|astazi|2026|aplic|aplica)\b",
    re.IGNORECASE,
)


def _chunk_year(c: RetrievedChunk) -> int | None:
    blob = f"{c.document_url or ''} {c.document_title or ''} {c.content or ''}"
    years = [int(y) for y in _YEAR_RE.findall(blob)]
    if not years:
        return None
    return max(years)


def _diversify_by_document(
    scored: list[tuple[float, RetrievedChunk]], *, limit: int = 8
) -> list[RetrievedChunk]:
    """Keep best chunk per document so listing answers see many announcements."""
    by_doc: dict[int, tuple[float, RetrievedChunk]] = {}
    for score, c in scored:
        prev = by_doc.get(c.document_id)
        if prev is None or score > prev[0]:
            by_doc[c.document_id] = (score, c)
    ranked = sorted(by_doc.values(), key=lambda x: x[0], reverse=True)
    return [c for _, c in ranked[:limit]]


def verify_evidence(
    chunks: list[RetrievedChunk],
    *,
    question: str = "",
    min_rerank: float = 0.22,
    min_dense: float = 0.48,
    min_overlap: float = 0.18,
    answer_mode: str = "fact",
    wants_list: bool | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    """Gate evidence — prefer multi-doc coverage for list/current questions."""
    if is_offtopic_question(question):
        return "missing", []

    if not chunks:
        return "missing", []

    from datetime import datetime

    try:
        from backend.ai.prompts import CHISINAU_TZ

        year_now = datetime.now(CHISINAU_TZ).year
    except Exception:  # noqa: BLE001
        year_now = datetime.now().year

    wants_current = bool(_CURRENTISH_Q.search(question or "")) or analyze_wants_current(
        question
    )
    list_mode = (
        wants_list
        if wants_list is not None
        else (analyze_wants_list(question) or answer_mode == "list")
    )
    job_q = is_job_question(question)

    scored: list[tuple[float, RetrievedChunk]] = []
    for c in chunks:
        body = (c.content or "").lower()
        body_f = fold(c.content or "")
        title_f = fold(c.document_title or "")
        if "[expire_date]" in body or "download is available until" in body:
            if len((c.content or "").strip()) < 400:
                continue

        # Chrome menus are noise ONLY when the user is not asking about that topic
        chrome_keys = [
            "dispozitiile pretorului",
            "cautati pe internet",
            "declaratia de raspundere manageriala",
        ]
        if not job_q:
            chrome_keys.append("functii vacante")
        chrome_hits = sum(1 for k in chrome_keys if fold(k) in body_f)

        title_body = f"{c.document_title or ''} {c.content or ''}"
        ov = _token_overlap(question, title_body)
        title_ov = _token_overlap(question, c.document_title or "")
        if chrome_hits >= 2 and title_ov < 0.25 and ov < 0.30:
            continue

        # Holiday vacation pages must not answer job-vacancy questions
        if job_q or re.search(r"concurs|func[tț]|vacant|aplic", question or "", re.I):
            if re.search(
                r"vacan[țt]e?[ai]?\s+de\s+var|gr[ăa]dini[țt]|copiilor\s+[îi]n\s+vacan|"
                r"organizarea\s+activit",
                title_body,
                re.I,
            ) and not re.search(
                r"func[tț](?:iei|ia|ii)\s+public|ocuparea\s+func|anun[țt].{0,40}concurs",
                title_body,
                re.I,
            ):
                continue

        past_event = bool(
            re.search(
                r"s-a\s+desf[ăa][sș]urat|a\s+fost\s+desf|"
                r"rezultatele\s+finale\s+vor\s+fi\s+anun|"
                r"desemnarea\s+[îi]nving|[îi]nving[aă]tori?(?:ului)?|"
                r"a\s+avut\s+loc\s+etapa",
                title_body,
                re.I,
            )
        )
        open_call = bool(
            re.search(
                r"anun[țtăa].{0,40}concurs|depune(?:rea)?\s+dosar|"
                r"până\s+(?:în|la)\s+data|se\s+prelung|aviz\s+concurs|"
                r"func[tț](?:iei|ia|ii)\s+public|posturi\s+vacante|"
                r"ocuparea\s+(?:unei\s+)?func|specialist",
                title_body,
                re.I,
            )
        )
        if wants_current and past_event and not open_call:
            continue
        # Winner / finished notices must never answer "open jobs now"
        if wants_current and past_event and job_q:
            continue

        rr = float(c.rerank_score or 0.0)
        ds = float(c.dense_score or 0.0)
        # Lexical title hits from SQL often carry high lexical_score
        lx = float(getattr(c, "lexical_score", 0) or 0.0)
        if (
            rr >= min_rerank
            or (ds >= min_dense and ov >= 0.08)
            or ov >= min_overlap
            or title_ov >= 0.28
            or lx >= 0.75
            or (job_q and open_call and (rr >= 0.15 or lx >= 0.5 or ds >= 0.4))
        ):
            score = max(rr, ds * 0.55, ov, lx * 0.5) + title_ov * 0.55
            if title_ov >= 0.4:
                score += 0.3
            if job_q:
                if re.search(r"anun[țt]|concurs|vacant|aviz", title_f):
                    score += 0.4
                if re.search(r"func[tț]|funct|specialist|dosar", title_f):
                    score += 0.2
                if open_call:
                    score += 0.15
            if chrome_hits >= 2:
                score -= 0.25
            if past_event and not open_call:
                score -= 0.4
            y = _chunk_year(c)
            if wants_current and y is not None:
                if y >= year_now:
                    score += 0.35
                elif y >= year_now - 1:
                    score += 0.02
                else:
                    score -= 0.45
            scored.append((score, c))

    if not scored:
        return "missing", []

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][0]
    if best < 0.18:
        return "missing", []

    # LIST / multi-item questions: never collapse to title-overlap-only peers
    if list_mode or answer_mode in ("list", "howto"):
        usable = _diversify_by_document(scored, limit=8)
    else:
        topical = [
            c
            for s, c in scored
            if _token_overlap(question, c.document_title or "") >= 0.28
        ]
        if topical and not wants_current:
            usable = topical[:6]
        else:
            # Score band — keep peers close to best so secondary docs survive
            usable = _diversify_by_document(
                [(s, c) for s, c in scored if s >= max(best * 0.45, 0.16)],
                limit=8,
            )
    if not usable:
        return "missing", []

    # Current questions: prefer this year; never present ancient-only as "now"
    if wants_current:
        fresh = [c for c in usable if (_chunk_year(c) or 0) >= year_now]
        if fresh:
            if list_mode:
                usable = fresh[:8]
            else:
                rest = [c for c in usable if c not in fresh]
                usable = (fresh + rest)[:8]
        else:
            recent = [c for c in usable if (_chunk_year(c) or 0) >= year_now - 1]
            if recent:
                usable = recent[:8]
            else:
                return "missing", []

    if question_about_deadline(question):
        by_doc: dict[int, set[int]] = defaultdict(set)
        for c in usable:
            days = _deadline_mentions(c.content)
            if days:
                by_doc[c.document_id].update(days)
        if len(by_doc) >= 2:
            sets = list(by_doc.values())
            if len({frozenset(s) for s in sets}) >= 2:
                return "conflict", usable

    return "supported", usable
