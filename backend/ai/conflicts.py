"""Find explicit numeric disagreements about the same municipal service."""

from __future__ import annotations

import re
from typing import Any, Protocol

from backend.ai.analyze import fold, is_job_question, tokens


class Evidence(Protocol):
    document_id: int
    document_title: str
    document_url: str | None
    content: str
    page: int | None


_FEE_QUESTION = re.compile(r"\b(tax(?:a|ă|e|ei|ele|elor)|tarif\w*|cost\w*|fee|price|сколько\s+стоит|стоимость|тариф\w*)\b", re.I)
_DURATION_QUESTION = re.compile(r"\b(termen\w*|durat\w*|c[aâ]t\s+dureaz[aă]|[îi]n\s+c[aâ]t\s+timp|how\s+long|deadline|processing\s+time|срок\w*)\b", re.I)
_DAYS = re.compile(r"\b(\d{1,3})\s*(?:de\s+)?(?:zile|zi|days?|дней|дня|день)\b", re.I)
_MONEY = re.compile(r"\b(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:lei|mdl|л(?:е|ё)ев)\b", re.I)
_TIME_CUE = re.compile(r"termen|durat|eliber|emit|solu[tț]ion|proces|deadline|processing|срок|выдач", re.I)
_FEE_CUE = re.compile(r"tax|tarif|cost|plat|achit|fee|price|стоим|тариф|оплат", re.I)
_QUALIFIER = re.compile(r"\b(urgent|urgen[tț][aă]|express|persoan[aă]\s+fizic[aă]|persoan[aă]\s+juridic[aă])\b", re.I)
_FIELD_ROOTS = {
    "terme", "durat", "elibe", "emite", "solut", "zile", "days", "taxa",
    "taxe", "taxei", "taxel", "tarif", "cost", "costu", "lei", "mdl", "price", "fee", "suma",
    "plati", "achit", "mult", "срок", "дней", "день", "стои", "тариф",
}


def _subject_roots(question: str) -> set[str]:
    roots = {word[:5] for word in tokens(question)}
    return {root for root in roots if root not in _FIELD_ROOTS and len(root) >= 4}


def conflict_field(question: str) -> str | None:
    if is_job_question(question):
        # Different vacancies legitimately have different deadlines and fees.
        return None
    if _FEE_QUESTION.search(question or ""):
        return "fee"
    if _DURATION_QUESTION.search(question or ""):
        return "duration_days"
    return None


def _claims(hit: Evidence, field: str, subject: set[str]) -> set[tuple[str, str, str]]:
    text = hit.content or ""
    pattern = _MONEY if field == "fee" else _DAYS
    cue = _FEE_CUE if field == "fee" else _TIME_CUE
    found: set[tuple[str, str, str]] = set()
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 100) : min(len(text), match.end() + 65)]
        if not cue.search(window):
            continue
        context = fold(f"{hit.document_title or ''} {window}")
        matches = sum(root in context for root in subject)
        if matches < min(2, len(subject)):
            continue
        amount = match.group(1).replace(",", ".")
        if field == "fee":
            amount = str(float(amount)).rstrip("0").rstrip(".") if "." in amount else amount
        qualifiers = sorted(
            fold(m.group(0))
            for m in _QUALIFIER.finditer(f"{hit.document_title} {window}")
        )
        if field == "duration_days":
            tail = fold(text[match.end() : match.end() + 25])
            if re.search(r"lucr|working|рабоч", tail):
                qualifiers.append("working_days")
            elif re.search(r"calendar|календар", tail):
                qualifiers.append("calendar_days")
        found.add((amount, window.strip()[:280], ",".join(qualifiers)))
    return found


def _document_year(hit: Evidence) -> str | None:
    years = re.findall(r"(?<!\d)20\d{2}(?!\d)", f"{hit.document_title or ''} {hit.document_url or ''}")
    return max(years) if years else None


def detect_document_conflicts(hits: list[Evidence], question: str) -> list[dict[str, Any]]:
    """Compare one clear claim per document, for a named subject and same field."""
    field = conflict_field(question)
    subject = _subject_roots(question)
    if not field or len(subject) < 2:
        return []
    grouped: dict[int, tuple[Evidence, set[tuple[str, str, str]]]] = {}
    for hit in hits:
        claims = _claims(hit, field, subject)
        if hit.document_id not in grouped or (claims and not grouped[hit.document_id][1]):
            grouped[hit.document_id] = (hit, set())
        grouped[hit.document_id][1].update(claims)

    candidates: list[tuple[Evidence, str, str, str]] = []
    for hit, claims in grouped.values():
        values = {(value, qualifier) for value, _, qualifier in claims}
        if len(values) != 1:
            continue
        value, qualifier = next(iter(values))
        quote = next(quote for claimed, quote, q in claims if claimed == value and q == qualifier)
        candidates.append((hit, value, quote, qualifier))

    conflicts: list[dict[str, Any]] = []
    for i, (left, left_value, left_quote, left_qualifier) in enumerate(candidates):
        for right, right_value, right_quote, right_qualifier in candidates[i + 1 :]:
            if left_value == right_value or left_qualifier != right_qualifier:
                continue
            if left.document_url and left.document_url == right.document_url:
                continue
            left_year, right_year = _document_year(left), _document_year(right)
            if left_year and right_year and left_year != right_year:
                continue
            unit = " lei" if field == "fee" else " zile"
            conflicts.append({
                "field": field,
                "left": {
                    "document": left.document_title,
                    "value": f"{left_value}{unit}",
                    "days": [int(left_value)] if field == "duration_days" else [],
                    "quote": left_quote,
                    "url": left.document_url,
                    "page": str(left.page) if left.page is not None else None,
                },
                "right": {
                    "document": right.document_title,
                    "value": f"{right_value}{unit}",
                    "days": [int(right_value)] if field == "duration_days" else [],
                    "quote": right_quote,
                    "url": right.document_url,
                    "page": str(right.page) if right.page is not None else None,
                },
            })
            if len(conflicts) >= 3:
                return conflicts
    return conflicts
