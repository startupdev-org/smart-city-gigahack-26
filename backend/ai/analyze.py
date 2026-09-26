"""Question analysis — shared mode/intent/topic extraction for the RAG pipeline.

Bipolar answers usually come from brittle keyword gates (miss paraphrases),
over-narrow title filters, and skipping research when only stale evidence scores.
This module centralizes a richer, diacritic-tolerant read of the user question.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_DIACRITICS = str.maketrans(
    {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
        "Ă": "A",
        "Â": "A",
        "Î": "I",
        "Ș": "S",
        "Ş": "S",
        "Ț": "T",
        "Ţ": "T",
    }
)


def fold(text: str) -> str:
    """Lowercase + strip Romanian diacritics for tolerant matching."""
    t = (text or "").lower().translate(_DIACRITICS)
    return "".join(
        c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c)
    )


_STOP = {
    "care",
    "sunt",
    "este",
    "pentru",
    "despre",
    "the",
    "and",
    "what",
    "where",
    "how",
    "are",
    "для",
    "что",
    "как",
    "ale",
    "din",
    "cu",
    "unei",
    "unui",
    "pot",
    "sa",
    "să",
    "la",
    "in",
    "în",
    "pe",
    "de",
    "ce",
    "mai",
    "sau",
    "cum",
    "now",
    "acum",
    "asta",
    "also",
    "please",
    "vreau",
    "as",
    "to",
    "of",
    "a",
    "o",
    "un",
    "una",
}


def tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9ёа-я]{3,}", fold(text))
        if w not in _STOP
    }


_LIST_RE = re.compile(
    r"\b("
    r"exist[aă]|deschis|deschise|list[aă]|care\s+sunt|ce\s+(?:func|concur|anunt|anunț|post)|"
    r"toate|c[aâ]te|cate|открыт|есть\s+ли|which\s+(?:jobs|vacancies|contests)|"
    r"what\s+(?:jobs|vacancies|positions)|la\s+care\s+pot|pot\s+(?:s[aă]\s+)?aplic|"
    r"unde\s+(?:pot\s+)?aplic|ce\s+posturi|enumer|spune[- ]mi\s+(?:toate|care)"
    r")\b",
    re.I,
)

_CURRENT_RE = re.compile(
    r"\b("
    r"acum|current|now|deschis|deschise|открыт|ast[aă]zi|astazi|"
    r"2026|în\s+prezent|in\s+prezent|disponibil|active|ongoing|"
    r"vacant[aăe]?|конкурс|aplic|aplica|angajar"
    r")\b",
    re.I,
)

_JOB_RE = re.compile(
    r"(?:"
    r"concurs|vacant|angajar|ваканс|job\s*opening|posturi?\s+vacant|"
    r"func[tț](?:ii|ia|ie|iei)?\s+public|"
    r"funct(?:ii|ia|ie|iei)?\s+public|"
    r"ocuparea\s+func|locuri\s+de\s+munc[aă]|"
    r"\baplic[aă]|\baplica\b|candidat(?:ur[aă])?"
    r")",
    re.I,
)

_CONTACT_RE = re.compile(
    r"\b(contact|telefon|email|e-mail|adresa|adres[aă]|date\s+de\s+contact|"
    r"cum\s+(?:le|îi|o|ii)\s+(?:pot\s+)?contact|куда\s+звонить|телефон|адрес|"
    r"контак)\b",
    re.I,
)

_AUTH_RE = re.compile(
    r"autoriz|construir|urbanism|разрешен|permit|building|certificat\s+de\s+urban",
    re.I,
)

_DEADLINE_RE = re.compile(
    r"\b(termen|deadline|срочн|срок|c[aâ]t\s+dureaz[aă]|cat\s+dureaza|"
    r"zile\s+lucr|[îi]n\s+c[aâ]t\s+timp|in\s+cat\s+timp)\b",
    re.I,
)


def detect_intent(question: str) -> str:
    q = question or ""
    if _DEADLINE_RE.search(q):
        return "deadline"
    if _CONTACT_RE.search(q):
        return "contact"
    if _AUTH_RE.search(q):
        return "autorizatie"
    if _JOB_RE.search(q):
        return "concurs"
    return "general"


def wants_list(question: str) -> bool:
    return bool(_LIST_RE.search(question or ""))


def wants_current(question: str) -> bool:
    return bool(_CURRENT_RE.search(question or ""))


def answer_mode(question: str, *, intent: str) -> str:
    """How the answer should be shaped — drives retrieval breadth & verifier."""
    if intent == "contact":
        return "contact"
    if intent == "deadline":
        return "deadline"
    if wants_list(question) or intent == "concurs":
        return "list"
    if re.search(r"\b(cum|how|как|pa[sș]i|procedure|procedur)\b", question or "", re.I):
        return "howto"
    return "fact"


def topic_terms(question: str, *, limit: int = 8) -> list[str]:
    """Distinctive search terms (folded), longest/first-preference."""
    toks = sorted(tokens(question), key=lambda w: (-len(w), w))
    # Keep original-ish forms from question for SQL ilike when useful
    raw = re.findall(r"[A-Za-zăâîșțĂÂÎȘŢțŢёа-яЁА-Я0-9]{4,}", question or "")
    out: list[str] = []
    seen: set[str] = set()
    for w in raw + toks:
        f = fold(w)
        if f in _STOP or f in seen or len(f) < 4:
            continue
        seen.add(f)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def overlap_score(question: str, text: str) -> float:
    q, t = tokens(question), tokens(text)
    if not q or not t:
        return 0.0
    return len(q & t) / max(1, len(q))


def is_job_question(question: str) -> bool:
    return detect_intent(question) == "concurs" or bool(_JOB_RE.search(question or ""))


def analyze_question_meta(
    question: str, *, ui_language: str | None = None
) -> dict[str, Any]:
    from backend.ai.language import resolve_answer_language

    lang_meta = resolve_answer_language(question, ui_language)
    intent = detect_intent(question)
    mode = answer_mode(question, intent=intent)
    wl = wants_list(question) or mode == "list"
    wc = wants_current(question)
    topics = topic_terms(question)
    return {
        "language": lang_meta["answer_language"],
        "language_meta": lang_meta,
        "intent": intent,
        "answer_mode": mode,
        "wants_list": wl,
        "wants_current": wc,
        "topic_terms": topics,
        "is_job": is_job_question(question),
    }
