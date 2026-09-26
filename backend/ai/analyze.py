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


_MUNICIPAL_HINT_RE = re.compile(
    r"(?:"
    r"primar|pretur|chi[sș]in[aă]u|municip|autoriz|urbanism|construir|"
    r"certificat|peti[tț]|sesizar|tax[aă]|impozit|parcaj|gunoi|salubriz|"
    r"concurs|func[tț]i|vacant|angajar|dgaurf|ghiseu|ghi[sș]eu|"
    r"contact|telefon|adres[aă]|program\s+de\s+lucru|act\s+necesar|"
    r"dispozi[tț]|hot[aă]r[aâ]r|regulament|e-permis|locuin|"
    r"botanica|buiucani|ciocana|r[aâ][sș]can|centru\s+sector|"
    r"gradinit|grădini[tț]|scol[aă]|școal|transport\s+public|"
    r"аптека|примар|претур|кишин|разрешен|налог|конкурс"
    r")",
    re.I,
)

_CLEAR_OFFTOPIC_RE = re.compile(
    r"(?:"
    r"cine\s+sunt\s+eu|who\s+am\s+i|как\s+меня\s+зовут|кто\s+я|"
    r"ce\s+(?:mi-ai|ti-am|ți-am|ti\s+am)\s+(?:scris|spus|zise)|"
    r"what\s+did\s+i\s+(?:say|write)|previous\s+message|istoric(ul)?\s+chat|"
    r"îți\s+amintești|iti\s+amintesti|remember\s+what|"
    r"spune[- ]mi\s+o\s+glum[aă]|tell\s+me\s+a\s+joke|ban[aă]n[aă]|pizza|"
    r"cum\s+te\s+cheam[aă]|what\s+is\s+your\s+name|who\s+are\s+you|"
    r"scrie[- ]mi\s+(?:un\s+)?(?:cod|script|poem)|write\s+(?:me\s+)?(?:code|poem)|"
    r"re[tț]et[aă]|recipe|cum\s+s[aă]\s+fac\s+bani|crypto|bitcoin|"
    r"vremea\s+la\s+paris|weather\s+in|capitala\s+fran[tț]|"
    r"hello\s*$|salutare\s*$|buna\s*$|hi\s*$|hey\s*$"
    r")",
    re.I,
)


def looks_municipal(question: str) -> bool:
    return bool(_MUNICIPAL_HINT_RE.search(question or ""))


def looks_clearly_offtopic(question: str) -> bool:
    q = (question or "").strip()
    if len(q) < 2:
        return True
    if _CLEAR_OFFTOPIC_RE.search(q):
        return True
    # Very short chit-chat without municipal terms
    if len(q) < 12 and not looks_municipal(q):
        return True
    return False


def offtopic_reply(lang: str = "ro") -> str:
    if lang == "ru":
        return (
            "Этот вопрос не относится к муниципальным услугам и документам "
            "Примэрии Кишинёва. CivicAI помогает только с темами городской администрации "
            "(разрешения, контакты, конкурсы, налоги, услуги). "
            "Пожалуйста, задайте вопрос по теме города."
        )
    if lang == "en":
        return (
            "This question is outside CivicAI's scope. I only help with Chișinău "
            "municipal topics (permits, contacts, public jobs, taxes, city services). "
            "Please ask something related to City Hall."
        )
    return (
        "Această întrebare nu ține de serviciile și documentele Primăriei Municipiului "
        "Chișinău. CivicAI te poate ajuta doar cu teme municipale "
        "(autorizații, contacte, concursuri/funcții publice, taxe, servicii). "
        "Te rog reformulează o întrebare legată de administrația locală."
    )


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
        "looks_municipal": looks_municipal(question),
        "looks_offtopic": looks_clearly_offtopic(question),
    }
