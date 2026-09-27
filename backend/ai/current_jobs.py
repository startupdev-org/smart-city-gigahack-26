"""Conservative checks for answers claiming that a vacancy is open today."""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol

from backend.ai.analyze import fold


class JobHit(Protocol):
    document_title: str
    document_url: str | None
    content: str


_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)|"
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)|"
    r"(?<!\d)(\d{1,2})\s*(?:de\s*)?"
    r"(" + "|".join(_MONTHS) + r")\s*(?:anul\s*)?(20\d{2})(?!\d)",
    re.I,
)
_DEADLINE_CUE_RE = re.compile(
    r"termen(?:ul|ului)?(?:\s*[-–]?\s*limit[aă])?\s+(?:de\s+)?"
    r"(?:depunere|inscriere|înscriere|inregistrare|înregistrare)|"
    r"data\s*[-–]?\s*limit[aă]|data\s+depunerii\s+dosarelor|"
    r"depunerea\s+(?:dosarelor|candidaturilor)|"
    r"dosarele\s+pot\s+fi\s+depuse|p[aâ]n[aă]\s+la\s+(?:data\s+de\s+)?|"
    r"application\s+deadline|apply\s+by|closing\s+date|"
    r"срок\s+подачи|при[её]м\s+документов\s+до",
    re.I,
)
_SECTORS = ("botanica", "buiucani", "ciocana", "rascani", "centru")


def _parse_date(match: re.Match[str]) -> date | None:
    groups = match.groups()
    try:
        if groups[0]:
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        if groups[3]:
            return date(int(groups[5]), int(groups[4]), int(groups[3]))
        return date(int(groups[8]), _MONTHS[groups[7].lower()], int(groups[6]))
    except (ValueError, KeyError):
        return None


def application_deadlines(text: str) -> list[date]:
    """Read dates near an application deadline cue, not publication dates."""
    normalized = fold(text or "")
    found: set[date] = set()
    for cue in _DEADLINE_CUE_RE.finditer(normalized):
        # A short window avoids unrelated publication/interview dates later on.
        window = normalized[cue.end() : cue.end() + 120].split("\n", 1)[0]
        for match in _DATE_RE.finditer(window):
            parsed = _parse_date(match)
            if parsed:
                found.add(parsed)
    return sorted(found)


def job_evidence_excerpt(text: str, *, limit: int = 2200) -> str:
    """Keep the announcement header and its deadline inside the LLM context."""
    if len(text) <= limit:
        return text
    normalized = fold(text)
    deadline_cues = [
        cue for cue in _DEADLINE_CUE_RE.finditer(normalized)
        if _DATE_RE.search(normalized[cue.end() : cue.end() + 120])
    ]
    if not deadline_cues or deadline_cues[0].start() < limit - 150:
        return text[:limit]
    start = max(0, deadline_cues[0].start() - 250)
    head = text[:500]
    return head + "\n…\n" + text[start : start + limit - len(head) - 3]


def current_job_state(hit: JobHit, *, today: date) -> str:
    """Return open, expired, or unverified. Never infer open from year alone."""
    blob = f"{hit.document_title or ''}\n{hit.content or ''}"
    deadlines = application_deadlines(blob)
    if not deadlines:
        return "unverified"
    if deadlines[-1] < today:
        return "expired"
    if deadlines[-1] == today:
        # A date alone does not say whether today's hour of submission passed.
        return "unverified"
    # Multiple distinct deadlines can be separate jobs on a listing page.
    if len(deadlines) > 1:
        return "unverified"
    return "open"


def sector_in_question(question: str) -> str | None:
    words = set(re.findall(r"[a-z]+", fold(question or "")))
    named = [sector for sector in _SECTORS if sector in words]
    return named[0] if len(named) == 1 else None


def job_hit_matches_sector(hit: JobHit, sector: str | None) -> bool:
    if not sector:
        return True
    title_url = fold(f"{hit.document_title or ''} {hit.document_url or ''}")
    named = {name for name in _SECTORS if name in title_url}
    if named:
        return named == {sector}
    body = fold(hit.content or "")
    mentioned = {name for name in _SECTORS if name in body}
    return mentioned == {sector} and bool(
        re.search(rf"pretur\w*\s+(?:sectorului\s+)?{sector}\b", body)
    )
