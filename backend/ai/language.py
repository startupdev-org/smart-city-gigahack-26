"""Answer / UI language helpers for CivicAI."""

from __future__ import annotations

import re

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_WORD_RE = re.compile(r"[A-Za-zăâîșțĂÂÎȘȚ]+")

_EN_HINTS = {
    "what",
    "where",
    "when",
    "how",
    "which",
    "who",
    "the",
    "is",
    "are",
    "can",
    "need",
    "please",
    "contact",
    "phone",
    "address",
    "permit",
    "building",
    "authorization",
    "deadline",
    "vacancy",
    "vacancies",
    "open",
    "current",
    "office",
    "city",
    "hall",
    "petition",
}

_RO_HINTS = {
    "care",
    "unde",
    "când",
    "cand",
    "cum",
    "ce",
    "sunt",
    "este",
    "pentru",
    "despre",
    "autorizație",
    "autorizatie",
    "construire",
    "contact",
    "telefon",
    "adresa",
    "adresă",
    "pretura",
    "primăria",
    "primaria",
    "termen",
    "funcții",
    "functii",
    "vacante",
    "petiție",
    "petitie",
}


def detect_question_language(question: str) -> tuple[str, float]:
    """Return (lang, confidence) for ro|ru|en based on the question text."""
    q = (question or "").strip()
    if not q:
        return "ro", 0.0
    if _CYRILLIC_RE.search(q):
        return "ru", 0.95

    words = [w.lower() for w in _LATIN_WORD_RE.findall(q)]
    if not words:
        return "ro", 0.2

    en = sum(1 for w in words if w in _EN_HINTS)
    ro = sum(1 for w in words if w in _RO_HINTS)
    # diacritics strongly suggest Romanian
    if any(c in q for c in "ăâîșțĂÂÎȘȚ"):
        ro += 2

    total = max(len(words), 1)
    if en >= 2 and en > ro:
        conf = min(0.95, 0.45 + en / total)
        return "en", conf
    if ro >= 1 and ro >= en:
        conf = min(0.95, 0.4 + ro / total)
        return "ro", conf
    if en == 1 and ro == 0 and len(words) <= 6:
        return "en", 0.55
    return "ro", 0.35


def resolve_answer_language(question: str, ui_language: str | None = None) -> dict:
    """
    Answer language follows the question when clear.
    UI language is only a soft preference when detection is ambiguous.
    """
    q_lang, conf = detect_question_language(question)
    ui = (ui_language or "").lower().strip()
    if ui not in ("ro", "ru", "en"):
        ui = None

    if conf >= 0.55:
        answer = q_lang
        source = "question"
    elif ui:
        answer = ui
        source = "ui_hint"
    else:
        answer = q_lang
        source = "question_weak"

    return {
        "answer_language": answer,
        "question_language": q_lang,
        "question_confidence": round(conf, 2),
        "ui_language": ui,
        "source": source,
    }


def language_instruction(meta: dict) -> str:
    names = {"ro": "Romanian", "ru": "Russian", "en": "English"}
    ans = names.get(meta.get("answer_language") or "ro", "Romanian")
    q = names.get(meta.get("question_language") or "ro", "Romanian")
    ui = meta.get("ui_language")
    ui_s = names.get(ui, "unknown") if ui else "not set"
    return (
        f"ANSWER LANGUAGE: write the full answer in {ans}.\n"
        f"Question appears to be in {q} "
        f"(confidence {meta.get('question_confidence', 0)}).\n"
        f"UI language preference (soft hint only, does NOT override a clear question language): {ui_s}.\n"
        f"If the user mixed languages, prefer {ans}."
    )
