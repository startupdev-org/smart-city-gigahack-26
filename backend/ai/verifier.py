from __future__ import annotations

import re
from collections import defaultdict

from backend.ai.analyze import (
    fold,
    is_job_question,
    overlap_score,
    tokens as analyze_tokens,
    wants_current as analyze_wants_current,
    wants_list as analyze_wants_list,
)
from backend.ai.current_jobs import current_job_state, job_hit_matches_sector, sector_in_question
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
    from backend.ai.analyze import (
        looks_clearly_offtopic,
        looks_identity_question,
    )

    return (
        bool(_OFFTOPIC_RE.search(question or ""))
        or looks_identity_question(question)
        or looks_clearly_offtopic(question)
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
    r"\b(acum|current|now|deschis|открыт|сейчас|vacant[ăaе]?|funcți[ei].*vacant|"
    r"angajar|job|astăzi|astazi|aplic|aplica)\b",
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


def _is_junk_chunk(c: RetrievedChunk) -> bool:
    """Drop captcha / chrome shells that never answer municipal questions."""
    title = (c.document_title or "").strip()
    body = c.content or ""
    blob = f"{title}\n{body[:600]}".lower()
    if re.search(
        r"confirm[aă]\s+c[aă]\s+nu\s+e[sș]ti\s+robot|captcha|cloudflare|"
        r"just\s+a\s+moment|attention\s+required|enable\s+javascript",
        blob,
        re.I,
    ):
        return True
    title_f = fold(title)
    if title_f in {"acte", "pagina oficiala", "home", "acasa"}:
        if len(re.sub(r"\s+", " ", body).strip()) < 280:
            return True
        if title_f == "acte" and not re.search(
            r"autoriza|construire|certificat\s+de\s+urban|e-permis|dosar",
            body,
            re.I,
        ):
            return True
    return False


def _content_overlap(question: str, content: str) -> float:
    return overlap_score(question, content or "")


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
    """Select evidence by content relevance — not generic short titles."""
    if is_offtopic_question(question):
        return "missing", []

    if not chunks:
        return "missing", []

    from datetime import datetime

    try:
        from backend.ai.prompts import CHISINAU_TZ

        today = datetime.now(CHISINAU_TZ).date()
    except Exception:  # noqa: BLE001
        today = datetime.now().date()
    year_now = today.year

    wants_current = bool(_CURRENTISH_Q.search(question or "")) or analyze_wants_current(
        question
    )
    list_mode = (
        wants_list
        if wants_list is not None
        else (analyze_wants_list(question) or answer_mode == "list")
    )
    job_q = is_job_question(question)
    target_sector = sector_in_question(question) if job_q else None
    q_toks = analyze_tokens(question)
    rich_q = len(q_toks) >= 2

    scored: list[tuple[float, RetrievedChunk]] = []
    for c in chunks:
        if job_q and not job_hit_matches_sector(c, target_sector):
            continue
        if job_q and wants_current and current_job_state(c, today=today) != "open":
            continue
        if _is_junk_chunk(c):
            continue
        body = (c.content or "").lower()
        body_f = fold(c.content or "")
        title_f = fold(c.document_title or "")
        title_len = len((c.document_title or "").strip())
        if "[expire_date]" in body or "download is available until" in body:
            if len((c.content or "").strip()) < 400:
                continue

        chrome_keys = [
            "dispozitiile pretorului",
            "cautati pe internet",
            "declaratia de raspundere manageriala",
        ]
        if not job_q:
            chrome_keys.append("functii vacante")
        chrome_hits = sum(1 for k in chrome_keys if fold(k) in body_f)

        title_body = f"{c.document_title or ''} {c.content or ''}"
        content_ov = _content_overlap(question, c.content or "")
        title_ov = _token_overlap(question, c.document_title or "")
        if title_len <= 12 and title_ov > 0 and content_ov < 0.12:
            title_ov *= 0.25
        if chrome_hits >= 2 and content_ov < 0.25:
            continue

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
        if wants_current and past_event and job_q:
            continue

        rr = float(c.rerank_score or 0.0)
        ds = float(c.dense_score or 0.0)
        lx = float(getattr(c, "lexical_score", 0) or 0.0)
        has_rr = c.rerank_score is not None

        # Cross-encoder is the main gate when present — refuse weak semantic matches
        if has_rr and rr < 0.18 and content_ov < 0.22:
            continue

        admits = (
            (has_rr and rr >= max(min_rerank, 0.28) and content_ov >= 0.05)
            or content_ov >= (0.18 if rich_q else min_overlap)
            or (not has_rr and ds >= min_dense and content_ov >= 0.12)
            or (title_ov >= 0.45 and content_ov >= 0.12 and title_len > 20)
            or (job_q and open_call and (content_ov >= 0.08 or lx >= 0.75 or rr >= 0.25))
            or (list_mode and open_call and (lx >= 0.9 or rr >= 0.3))
        )
        if not admits:
            continue

        score = (
            (rr * 1.6 if has_rr else 0.0)
            + content_ov * 1.1
            + (ds or 0) * 0.25
            + title_ov * 0.15
        )
        if title_ov >= 0.45 and title_len > 24:
            score += 0.15
        if job_q:
            if re.search(r"anun[țt]|concurs|vacant|aviz|posturi\s+vacante", title_f):
                score += 0.25
            if open_call:
                score += 0.12
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

    best_rr = max((float(c.rerank_score or 0) for _, c in scored), default=0.0)
    best_cov = max(_content_overlap(question, c.content or "") for _, c in scored)
    # Semantically weak pool → missing (don't feed construction-news as permits)
    if best_rr > 0 and best_rr < 0.22 and best_cov < 0.16 and not list_mode:
        return "missing", []

    if list_mode or answer_mode in ("list", "howto"):
        usable = _diversify_by_document(scored, limit=8)
    else:
        strong = [
            (s, c)
            for s, c in scored
            if _content_overlap(question, c.content or "") >= 0.12
            or (
                _token_overlap(question, c.document_title or "") >= 0.4
                and len((c.document_title or "").strip()) > 24
            )
        ]
        band = strong if strong else [
            (s, c) for s, c in scored if s >= max(best * 0.5, 0.16)
        ]
        usable = _diversify_by_document(band, limit=6)

    if not usable:
        return "missing", []

    best_cov = max(_content_overlap(question, h.content or "") for h in usable)
    if rich_q and best_cov < 0.10 and not list_mode:
        return "missing", []

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
