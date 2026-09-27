"""Recognize short model answers that say the evidence did not answer the question."""

import re


_MISSING_CLAIM_RE = re.compile(
    r"(?:"
    r"\bnu\s+(?:am\s+|a\s+fost\s+|s-(?:a|au)\s+|au\s+fost\s+)?"
    r"(?:identificat[ăae]?|g[ăa]sit[ăae]?|disponibil[ăae]?)\b|"
    r"\binforma[țt]i(?:a|ile)\s+nu\s+(?:a\s+fost|au\s+fost|este|sunt)\b|"
    r"\bnu\s+exist[ăa]\s+(?:informa[țt]ii|detalii|date)\b|"
    r"\bnot\s+found\s+in\s+(?:the\s+)?(?:available\s+)?(?:municipal\s+)?corpus\b|"
    r"\bno\s+(?:current|matching|relevant|available)\s+"
    r"(?:information|details|announcement)\b|"
    r"\bинформаци[яи]\s+не\s+найден\w*\b|"
    r"\bstatus\s*[:=]\s*missing\b"
    r")",
    re.I,
)


def answer_claims_missing(answer: str) -> bool:
    """Detect a brief lack-of-evidence reply, without treating cited facts as misses."""
    value = (answer or "").strip()
    if not value:
        return True
    if re.fullmatch(r"missing|lips[aă]|не\s+найдено|not\s+found\.?", value, re.I):
        return True
    if len(value) >= 280 or re.search(r"\[\d+\]", value):
        return False
    return bool(_MISSING_CLAIM_RE.search(value))
