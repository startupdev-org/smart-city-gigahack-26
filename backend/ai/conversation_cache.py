"""Conservative reuse of a sourced answer from the same conversation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from backend.ai.analyze import detect_intent, fold, is_job_question, wants_current
from backend.ai.conflicts import conflict_field

_MAX_AGE = timedelta(hours=24)
_TIME_SENSITIVE_RE = re.compile(
    r"\b(today|tomorrow|yesterday|latest|recent|currently|this\s+(?:week|month|year)|"
    r"ast[aă]zi|m[aâ]ine|ieri|ultim|recent|s[aă]pt[aă]m[aâ]n|luna\s+aceasta|"
    r"anul\s+acesta|сегодня|завтра|вчера|сейчас|последн|недел)\b",
    re.I,
)
_FOLLOWUP_RE = re.compile(
    r"^\s*(?:dar|și|si|and|what\s+about|а\s+в)\b|"
    r"\b(?:asta|acesta|aceasta|acelea|that|those|it)\b",
    re.I,
)


def _key(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9а-яё]+", fold(question or "")))


def _cacheable(question: str) -> bool:
    return bool(
        len(_key(question).split()) >= 4
        and not is_job_question(question)
        and not wants_current(question)
        and detect_intent(question) != "deadline"
        and conflict_field(question) is None
        and not _TIME_SENSITIVE_RE.search(question)
        and not _FOLLOWUP_RE.search(question)
    )


def find_prior_answer(
    messages: Sequence[Any], question: str, *, now: datetime | None = None
) -> Any | None:
    """Return a recent sourced assistant message for an equivalent prior question.

    Messages must be ordered oldest first and belong to one authorized session.
    Only normalized repeat questions are accepted; paraphrases need fresh retrieval.
    """
    if not _cacheable(question):
        return None
    now = now or datetime.now(timezone.utc)
    key = _key(question)
    for user_message, assistant_message in reversed(list(zip(messages, messages[1:]))):
        if user_message.role != "user" or assistant_message.role != "assistant":
            continue
        if _key(user_message.content) != key:
            continue
        if assistant_message.status != "supported" or not assistant_message.sources_json:
            continue
        created = assistant_message.created_at
        if not created:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if timedelta(0) <= now - created <= _MAX_AGE:
            return assistant_message
    return None
