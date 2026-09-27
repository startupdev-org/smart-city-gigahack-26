"""Resolve short sector follow-ups using the preceding question's topic."""

from __future__ import annotations

import re

from backend.ai.analyze import is_job_question, wants_current
from backend.ai.current_jobs import sector_in_question


_FOLLOWUP_RE = re.compile(r"^\s*(?:dar|și|si|what\s+about|and|а\s+в)\b", re.I)


def contextualize_question(question: str, previous_question: str | None) -> str:
    """Supply a missing job topic only for an explicitly elliptical follow-up."""
    if not previous_question or not _FOLLOWUP_RE.search(question or ""):
        return question
    if is_job_question(question) or not is_job_question(previous_question):
        return question
    sector = sector_in_question(question)
    if not sector:
        return question
    if re.match(r"^\s*(?:what\s+about|and)\b", question, re.I):
        current = " now" if wants_current(previous_question) else ""
        return f"What job openings are available{current} in {sector.capitalize()} sector?"
    current = " deschise acum" if wants_current(previous_question) else ""
    return f"Există concursuri publice{current} în sectorul {sector.capitalize()}?"
