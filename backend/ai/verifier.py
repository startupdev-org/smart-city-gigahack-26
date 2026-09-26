from __future__ import annotations

import re
from collections import defaultdict

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
    return bool(_OFFTOPIC_RE.search(question or ""))


def question_about_deadline(question: str) -> bool:
    return bool(_TERM_Q_RE.search(question or ""))


def is_generic_assistant_blurb(answer: str) -> bool:
    return bool(_GENERIC_ASSISTANT_RE.search(answer or ""))


def _deadline_mentions(text: str) -> set[int]:
    return {int(m.group(1)) for m in _DAY_RE.finditer(text or "")}


def _token_overlap(question: str, text: str) -> float:
    def toks(s: str) -> set[str]:
        return {
            w
            for w in re.findall(r"[a-zăâîșțёа-я0-9]{3,}", (s or "").lower())
            if w
            not in {
                "pentru",
                "despre",
                "care",
                "este",
                "sunt",
                "din",
                "the",
                "and",
                "для",
                "что",
                "ale",
                "sau",
                "cum",
                "mai",
                "cadrul",
                "secția",
                "sectia",
            }
        }

    q, t = toks(question), toks(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


_YEAR_RE = re.compile(r"(?:/|[^0-9])(20\d{2})(?:/|[^0-9])")
_CURRENTISH_Q = re.compile(
    r"\b(acum|current|now|deschis|открыт|vacant[ăaе]?|конкурс|funcți[ei].*vacant|"
    r"angajar|job|astăzi|astazi|2026)\b",
    re.IGNORECASE,
)


def _chunk_year(c: RetrievedChunk) -> int | None:
    blob = f"{c.document_url or ''} {c.document_title or ''} {c.content or ''}"
    years = [int(y) for y in _YEAR_RE.findall(blob)]
    if not years:
        return None
    return max(years)


def verify_evidence(
    chunks: list[RetrievedChunk],
    *,
    question: str = "",
    min_rerank: float = 0.22,
    min_dense: float = 0.48,
    min_overlap: float = 0.22,
) -> tuple[str, list[RetrievedChunk]]:
    """Strict gate — prefer missing over irrelevant citations."""
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

    wants_current = bool(_CURRENTISH_Q.search(question or ""))

    scored: list[tuple[float, RetrievedChunk]] = []
    for c in chunks:
        # Skip download-manager chrome / placeholder junk
        body = (c.content or "").lower()
        if "[expire_date]" in body or "download is available until" in body:
            if len((c.content or "").strip()) < 400:
                continue
        # Skip heavily chrome-polluted chunks (menu dumps without article body)
        chrome_hits = sum(
            1
            for k in (
                "dispozițiile pretorului",
                "dispozitiile pretorului",
                "căutați pe internet",
                "cautati pe internet",
                "declarația de răspundere managerială",
                "declaratia de raspundere manageriala",
                "funcții vacante",
                "functii vacante",
            )
            if k in body
        )
        title_body = f"{c.document_title or ''} {c.content or ''}"
        ov = _token_overlap(question, title_body)
        title_ov = _token_overlap(question, c.document_title or "")
        # If chrome dominates and title doesn't match the question, drop
        if chrome_hits >= 2 and title_ov < 0.25 and ov < 0.35:
            continue

        rr = float(c.rerank_score or 0.0)
        ds = float(c.dense_score or 0.0)
        if rr >= min_rerank or (ds >= min_dense and ov >= 0.1) or ov >= min_overlap or title_ov >= 0.35:
            score = max(rr, ds * 0.55, ov) + title_ov * 0.55
            # boost strong title matches (project / event names)
            if title_ov >= 0.4:
                score += 0.3
            if chrome_hits >= 2:
                score -= 0.2
            y = _chunk_year(c)
            if wants_current and y is not None:
                if y >= year_now:
                    score += 0.25
                elif y >= year_now - 1:
                    score += 0.05
                else:
                    score -= 0.35
            scored.append((score, c))

    if not scored:
        return "missing", []

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][0]
    if best < 0.20:
        return "missing", []

    # Prefer tightly topical set: keep high title-overlap peers when available
    topical = [c for s, c in scored if _token_overlap(question, c.document_title or "") >= 0.3]
    if topical:
        usable = topical[:4]
    else:
        usable = [c for s, c in scored if s >= max(best * 0.55, 0.18)][:4]
    if not usable:
        return "missing", []

    # Current vacancy/event questions: drop clearly outdated peers when a fresh hit exists
    if wants_current:
        fresh = [c for c in usable if (_chunk_year(c) or 0) >= year_now]
        if fresh:
            usable = fresh
        else:
            # only old docs — better missing than presenting 2024 as "now"
            old_only = all((_chunk_year(c) or 0) < year_now - 0 for c in usable)
            if old_only and all((_chunk_year(c) or year_now) <= year_now - 2 for c in usable):
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
