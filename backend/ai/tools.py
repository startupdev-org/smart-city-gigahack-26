"""CivicAI agent tools — deterministic tools exposed in the chat stream UI."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from backend.ai.analyze import (
    analyze_question_meta,
    fold,
    topic_terms as extract_topic_terms,
)
from backend.ai.prompts import CHISINAU_TZ
from backend.ai.retrieval import HybridRetriever, RetrievedChunk
from backend.ai.verifier import (
    _chunk_year,
    _deadline_mentions,
    _token_overlap,
    question_about_deadline,
    verify_evidence,
)
from backend.crawler.html_parser import extract_html
from backend.db.models import Chunk, Document, DocumentChange, Source, TopicLink

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)
_PHONE_RE = re.compile(
    r"(?:\+?373[\s\-]?)?(?:0?\d{2})[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}"
    r"|(?:\(?0?\d{2}\)?[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2})",
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_ADDR_RE = re.compile(
    r"(?:str\.|strada|bd\.|bulevardul|aleea)\s+[^\n,;]{3,60}",
    re.I,
)
_VACANCY_RE = re.compile(
    r"(funcț(?:ii|ia)\s+vacant|anunț\s+cu\s+privire|concurs(?:ului)?|"
    r"ocuparea\s+funcț|probei\s+scrise|interviului\s+în\s+cadrul)",
    re.I,
)
_CONTACT_Q_RE = re.compile(
    r"\b(contact|telefon|email|e-mail|adresa|adresă|date\s+de\s+contact|"
    r"cum\s+(?:le|îi|o)\s+(?:pot\s+)?contact|куда\s+звонить|телефон|адрес|"
    r"контак)\b",
    re.I,
)

# Curated official contacts (fallback when corpus is noisy)
INSTITUTION_CONTACTS: dict[str, dict[str, str]] = {
    "botanica": {
        "name": "Pretura sectorului Botanica",
        "address": "str. Teilor nr. 10, Chișinău",
        "phone": "022 76-75-75",
        "email": "pretura.botanica@pmc.md",
        "url": "https://botanica.md/",
    },
    "centru": {
        "name": "Pretura sectorului Centru",
        "address": "str. Columna 147, Chișinău",
        "phone": "022 22-26-32",
        "email": "pretura.centru@pmc.md",
        "url": "https://www.chisinau.md/",
    },
    "buiucani": {
        "name": "Pretura sectorului Buiucani",
        "address": "str. Ion Creangă 4/2, Chișinău",
        "phone": "022 74-94-40",
        "email": "pretura.buiucani@pmc.md",
        "url": "https://www.chisinau.md/",
    },
    "ciocana": {
        "name": "Pretura sectorului Ciocana",
        "address": "str. Mircea cel Bătrân 4/2, Chișinău",
        "phone": "022 31-55-91",
        "email": "pretura.ciocana@pmc.md",
        "url": "https://www.chisinau.md/",
    },
    "rascani": {
        "name": "Pretura sectorului Râșcani",
        "address": "str. Kiev 147A, Chișinău",
        "phone": "022 44-01-12",
        "email": "pretura.rascani@pmc.md",
        "url": "https://www.chisinau.md/",
    },
    "primarie": {
        "name": "Primăria Municipiului Chișinău — Ghișeul Unic",
        "address": "bd. Ștefan cel Mare și Sfânt 83, Chișinău",
        "phone": "+373 22 20 15 05",
        "email": "primaria@pmc.md",
        "url": "https://www.chisinau.md/",
    },
    "dgaurf": {
        "name": "DGAURF",
        "address": "Chișinău",
        "phone": "+373 68 675 889",
        "email": "dgaurf@cmc.md",
        "url": "https://dgaurf.md/ro/regulatory",
    },
}

TOOL_CATALOG = [
    {"name": "analyze_question", "optional": False, "label_ro": "Analizez întrebarea", "label_ru": "Анализирую вопрос", "label_en": "Analyzing question"},
    {"name": "detect_institution", "optional": False, "label_ro": "Identific instituția", "label_ru": "Определяю учреждение", "label_en": "Detecting institution"},
    {"name": "build_search_query", "optional": False, "label_ro": "Reformulez căutarea", "label_ru": "Переформулирую запрос", "label_en": "Building search query"},
    {"name": "search_corpus", "optional": False, "label_ro": "Caut în corpus", "label_ru": "Ищу в корпусе", "label_en": "Searching corpus"},
    {"name": "filter_noise_docs", "optional": False, "label_ro": "Elimin zgomotul", "label_ru": "Убираю шум", "label_en": "Filtering noise"},
    {"name": "filter_by_year", "optional": False, "label_ro": "Filtrez după an", "label_ru": "Фильтрую по году", "label_en": "Filtering by year"},
    {"name": "verify_evidence", "optional": False, "label_ro": "Verific evidența", "label_ru": "Проверяю доказательства", "label_en": "Verifying evidence"},
    {"name": "expand_search_queries", "optional": True, "label_ro": "Generez cuvinte-cheie", "label_ru": "Генерирую ключевые слова", "label_en": "Expanding search keywords"},
    {"name": "research_corpus", "optional": True, "label_ro": "Recaut cu asumții", "label_ru": "Повторный поиск", "label_en": "Researching with assumptions"},
    {"name": "extract_contact_fields", "optional": True, "label_ro": "Extrag telefoane/email", "label_ru": "Извлекаю контакты", "label_en": "Extracting phones/email"},
    {"name": "lookup_known_contacts", "optional": True, "label_ro": "Consult contacte cunoscute", "label_ru": "Сверяю известные контакты", "label_en": "Looking up known contacts"},
    {"name": "classify_sources", "optional": False, "label_ro": "Clasific sursele", "label_ru": "Классифицирую источники", "label_en": "Classifying sources"},
    {"name": "detect_conflicts", "optional": True, "label_ro": "Detectez conflicte", "label_ru": "Ищу противоречия", "label_en": "Detecting conflicts"},
    {"name": "fetch_url", "optional": True, "label_ro": "Extrag conținut din link", "label_ru": "Загружаю содержимое ссылки", "label_en": "Fetching URL content"},
    {"name": "resolve_contact", "optional": False, "label_ro": "Găsesc pagina de contact", "label_ru": "Ищу контактную страницу", "label_en": "Resolving contact page"},
    {"name": "estimate_confidence", "optional": False, "label_ro": "Estimez încrederea", "label_ru": "Оцениваю уверенность", "label_en": "Estimating confidence"},
    {"name": "corpus_health", "optional": True, "label_ro": "Verific starea corpusului", "label_ru": "Проверяю корпус", "label_en": "Checking corpus health"},
    {"name": "read_document", "optional": True, "label_ro": "Citesc documentul complet", "label_ru": "Читаю документ", "label_en": "Reading full document"},
    {"name": "read_document_chunks", "optional": True, "label_ro": "Citesc pasajele documentului", "label_ru": "Читаю фрагменты", "label_en": "Reading document chunks"},
    {"name": "find_document_by_url", "optional": True, "label_ro": "Caut document după URL", "label_ru": "Ищу документ по URL", "label_en": "Finding document by URL"},
    {"name": "refresh_document", "optional": True, "label_ro": "Reîmprospătez documentul din sursă", "label_ru": "Обновляю документ", "label_en": "Refreshing document from source"},
    {"name": "list_recent_documents", "optional": True, "label_ro": "Listez documente recente", "label_ru": "Список новых документов", "label_en": "Listing recent documents"},
    {"name": "extract_dates_deadlines", "optional": True, "label_ro": "Extrag termene și date", "label_ru": "Извлекаю сроки", "label_en": "Extracting dates & deadlines"},
    {"name": "lookup_topic_link", "optional": True, "label_ro": "Găsesc pagina oficială pe temă", "label_ru": "Ищу тему/страницу", "label_en": "Looking up topic page"},
    {"name": "search_exact_phrase", "optional": True, "label_ro": "Caut frază exactă", "label_ru": "Ищу точную фразу", "label_en": "Exact phrase search"},
    {"name": "get_document_changes", "optional": True, "label_ro": "Istoric schimbări document", "label_ru": "История изменений", "label_en": "Document change history"},
    {"name": "source_coverage", "optional": True, "label_ro": "Acoperire pe surse", "label_ru": "Покрытие источников", "label_en": "Source coverage stats"},
    {"name": "read_multi_documents", "optional": True, "label_ro": "Citesc mai multe documente", "label_ru": "Читаю несколько документов", "label_en": "Reading multiple documents"},
    {"name": "expand_related_chunks", "optional": True, "label_ro": "Extind pasaje din aceleași documente", "label_ru": "Расширяю фрагменты", "label_en": "Expanding related chunks"},
    {"name": "broaden_corpus_search", "optional": True, "label_ro": "Extind căutarea pe tot corpusul", "label_ru": "Расширяю поиск", "label_en": "Broadening corpus search"},
]


def classify_doc_type(title: str, url: str | None, content: str = "") -> str:
    blob = f"{title} {url or ''} {content[:200]}".lower()
    if any(k in blob for k in ("contact", "telefon", "email", "adresa", "adresă")):
        return "contact"
    if any(k in blob for k in ("dispoziț", "disposi", "распоряж", "decizie", "hotărâre", "hotarare")):
        return "decizie"
    if any(k in blob for k in ("regulament", "codul", "lege", "normativ", "e-permis", "pasaport")):
        return "regulament"
    if any(k in blob for k in ("anunț", "anunt", "concurs", "vacant", "noutăț", "comunicat")):
        return "anunt"
    if any(k in blob for k in (".pdf", "anexa", "formular", "ghid")):
        return "document"
    return "pagina"


def question_about_contact(question: str) -> bool:
    return bool(_CONTACT_Q_RE.search(question or ""))


def _now_year() -> int:
    try:
        return datetime.now(CHISINAU_TZ).year
    except Exception:  # noqa: BLE001
        return datetime.now().year


@dataclass
class ToolEvent:
    name: str
    status: str  # start | done | error
    label_ro: str
    label_ru: str
    label_en: str = ""
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ms: int = 0
    optional: bool = False


@dataclass
class AgentState:
    question: str
    language: str = "ro"
    ui_language: str | None = None
    language_meta: dict[str, Any] = field(default_factory=dict)
    intent: str = "general"
    answer_mode: str = "fact"
    wants_list: bool = False
    topic_terms: list[str] = field(default_factory=list)
    institution: str | None = None
    wants_current: bool = False
    urls_in_question: list[str] = field(default_factory=list)
    search_query: str = ""
    alt_queries: list[str] = field(default_factory=list)
    hits: list[RetrievedChunk] = field(default_factory=list)
    gate: str = "missing"
    usable: list[RetrievedChunk] = field(default_factory=list)
    source_meta: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    fetched: list[dict[str, Any]] = field(default_factory=list)
    contact: dict[str, Any] | None = None
    extracted_contacts: dict[str, Any] = field(default_factory=dict)
    known_contact: dict[str, Any] | None = None
    confidence: str = "low"
    confidence_score: float = 0.0
    health: dict[str, Any] = field(default_factory=dict)
    tools_run: list[str] = field(default_factory=list)
    contact_answer: str | None = None


def _meta(name: str) -> dict[str, Any]:
    for t in TOOL_CATALOG:
        if t["name"] == name:
            return t
    return {
        "name": name,
        "label_ro": name,
        "label_ru": name,
        "label_en": name,
        "optional": False,
    }


def run_tool(name: str, fn: Callable[[], Any]) -> tuple[Any, ToolEvent]:
    m = _meta(name)
    t0 = time.perf_counter()
    try:
        result = fn()
        ms = int((time.perf_counter() - t0) * 1000)
        detail = ""
        data: dict[str, Any] = {}
        if isinstance(result, dict):
            detail = str(result.get("summary") or result.get("detail") or "")[:220]
            data = {k: v for k, v in result.items() if k not in ("summary",)}
        elif isinstance(result, list):
            detail = f"{len(result)} rezultate"
            data = {"count": len(result)}
        else:
            detail = str(result)[:220]
        return result, ToolEvent(
            name=name,
            status="done",
            label_ro=m["label_ro"],
            label_ru=m["label_ru"],
            label_en=m.get("label_en") or m["label_ro"],
            detail=detail,
            data=data,
            ms=ms,
            optional=bool(m.get("optional")),
        )
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        logger.exception("tool %s failed", name)
        return None, ToolEvent(
            name=name,
            status="error",
            label_ro=m["label_ro"],
            label_ru=m["label_ru"],
            label_en=m.get("label_en") or m["label_ro"],
            detail=str(exc)[:180],
            ms=ms,
            optional=bool(m.get("optional")),
        )


def _start_event(name: str, detail: str = "") -> ToolEvent:
    m = _meta(name)
    return ToolEvent(
        name=name,
        status="start",
        label_ro=m["label_ro"],
        label_ru=m["label_ru"],
        label_en=m.get("label_en") or m["label_ro"],
        detail=detail,
        optional=bool(m.get("optional")),
    )


def tool_analyze_question(
    question: str, *, ui_language: str | None = None
) -> dict[str, Any]:
    meta = analyze_question_meta(question, ui_language=ui_language)
    urls = _URL_RE.findall(question or "")
    # Contact regex in tools may catch more phrasings than analyze module
    if question_about_contact(question):
        meta["intent"] = "contact"
        meta["answer_mode"] = "contact"
    return {
        "summary": (
            f"Q={meta['language_meta']['question_language']}; "
            f"answer={meta['language']}; "
            f"mode={meta['answer_mode']}; "
            f"intent={meta['intent']}; "
            f"list={'da' if meta['wants_list'] else 'nu'}; "
            f"current={'da' if meta['wants_current'] else 'nu'}"
        ),
        "language": meta["language"],
        "language_meta": meta["language_meta"],
        "intent": meta["intent"],
        "answer_mode": meta["answer_mode"],
        "wants_list": meta["wants_list"],
        "wants_current": meta["wants_current"],
        "topic_terms": meta["topic_terms"],
        "urls": urls,
        "year_now": _now_year(),
    }


def tool_detect_institution(question: str) -> dict[str, Any]:
    q = (question or "").lower()
    key = None
    if re.search(r"botanic", q):
        key = "botanica"
    elif re.search(r"buiucan", q):
        key = "buiucani"
    elif re.search(r"ciocan", q):
        key = "ciocana"
    elif re.search(r"r[aâ][sș]can|рышкан", q):
        key = "rascani"
    elif re.search(r"\bcentr[uŭ]|центр\b", q) and re.search(r"pretur|претур", q):
        key = "centru"
    elif re.search(r"dgaurf|urbanism|arhitect", q):
        key = "dgaurf"
    elif re.search(r"prim[aă]rie|примар", q):
        key = "primarie"
    elif re.search(r"pretur|претур", q):
        # pretura without sector — leave None
        key = None
    info = INSTITUTION_CONTACTS.get(key or "", {})
    return {
        "summary": info.get("name") or (key or "Instituție neidentificată"),
        "institution": key,
        "name": info.get("name"),
    }


def tool_build_search_query(
    question: str, *, intent: str, institution: str | None
) -> dict[str, Any]:
    if intent == "concurs":
        parts = [
            "concurs pentru ocuparea funcției publice vacante",
            "anunț dosar specialist",
            "funcții publice vacante",
            "AVIZ CONCURS",
        ]
        if institution and institution in INSTITUTION_CONTACTS:
            parts.insert(0, INSTITUTION_CONTACTS[institution]["name"])
        extra = extract_topic_terms(question, limit=6)
        stops = {
            "există",
            "exista",
            "pentru",
            "despre",
            "acum",
            "deschise",
            "public",
            "publice",
            "vacante",
        }
        parts.extend([w for w in extra if fold(w) not in {fold(s) for s in stops}][:5])
        query = " ".join(dict.fromkeys(parts))
        return {"summary": f"Query concurs: {query[:90]}…", "query": query}
    if intent == "autorizatie":
        parts = [
            "autorizație de construire",
            "certificat de urbanism",
            question,
        ]
        query = " ".join(dict.fromkeys(p for p in parts if p))
        return {"summary": f"Query autorizație: {query[:90]}…", "query": query}
    if intent != "contact":
        topics = extract_topic_terms(question, limit=6)
        if topics and len(question or "") < 40:
            query = f"{question} {' '.join(topics[:3])}"
            return {"summary": f"Query: {query[:90]}…", "query": query}
        return {"summary": "Query original", "query": question}
    parts = ["date de contact telefon email adresă"]
    if institution and institution in INSTITUTION_CONTACTS:
        parts.append(INSTITUTION_CONTACTS[institution]["name"])
        parts.append(institution)
    else:
        parts.append(question)
    if re.search(r"pretur", question or "", re.I):
        parts.append("pretura")
    query = " ".join(parts)
    return {"summary": f"Query: {query[:80]}…", "query": query}


def tool_search_corpus(
    db: Session,
    question: str,
    top_k: int = 5,
    *,
    intent: str = "general",
    answer_mode: str = "fact",
    topic_terms: list[str] | None = None,
) -> dict[str, Any]:
    wide = intent == "concurs" or answer_mode == "list"
    k = top_k + 6 if wide else top_k
    hits: list[RetrievedChunk] = []
    hybrid_err = None
    try:
        hits = HybridRetriever(db).search(question, top_k=k)
    except Exception as exc:  # noqa: BLE001
        hybrid_err = str(exc)[:120]
        logger.warning("hybrid search failed, lexical fallback: %s", hybrid_err)
    # Title/URL lexical boost for vacancy contests (hybrid often misses short anunț pages)
    if intent == "concurs":
        title_hits = _lexical_concurs_hits(db, limit=10)
        hits = _merge_hits(title_hits, hits, limit=max(k, 10))
    # General topic title rescue — any mode, when hybrid underranks exact titles
    if topic_terms:
        topic_hits = _lexical_topic_hits(db, topic_terms, limit=6)
        if topic_hits:
            hits = _merge_hits(topic_hits, hits, limit=max(k, 10))
    if not hits and intent == "concurs":
        hits = _lexical_concurs_hits(db, limit=max(8, top_k))
    summary = f"{len(hits)} pasaje găsite"
    if hybrid_err:
        summary += " (lexical fallback)"
    return {
        "summary": summary,
        "hits": hits,
        "titles": [h.document_title for h in hits[:5]],
    }


def _lexical_concurs_hits(db: Session, *, limit: int = 8) -> list[RetrievedChunk]:
    """Direct SQL over document titles — finds anunțuri that embeddings underrank.

    Hub listing pages (posturi-vacante) are fetched first so they are not buried
    under dozens of newer single-contest AVIZ rows.
    """
    noise = (
        ~Document.title.ilike("%vacanț%de var%")
        & ~Document.title.ilike("%vacanta%de var%")
        & ~Document.title.ilike("%grădini%")
        & ~Document.title.ilike("%gradinit%")
        & ~Document.title.ilike("%copiilor%")
    )
    hub_rows = (
        db.query(Document)
        .filter(
            (
                Document.url.ilike("%posturi-vacante%")
                | Document.url.ilike("%functii-vacante%")
                | Document.url.ilike("%posturi_vacante%")
                | Document.title.ilike("%posturi vacante%")
                | Document.title.ilike("%funcții vacante%")
                | Document.title.ilike("%functii vacante%")
                | Document.title.ilike("%funcţii vacante%")
            )
            & noise
        )
        .order_by(Document.id.desc())
        .limit(40)
        .all()
    )

    def _hub_quality(d: Document) -> tuple[int, int]:
        c = d.content or ""
        # Prefer pages that actually list current-year vacancy announcements
        year_hits = len(re.findall(r"20(?:2[5-9]|[3-9]\d)", c[:8000]))
        job_hits = len(
            re.findall(
                r"ocuparea\s+func|specialist|depune(?:rea)?\s+dosar|anun[țt].{0,40}concurs",
                c[:8000],
                re.I,
            )
        )
        url_bonus = 5 if "posturi-vacante" in (d.url or "").lower() else 0
        url_bonus += 4 if "chisinau.md" in (d.url or "").lower() else 0
        # Deprioritize paginated empty-ish listing shells
        if re.search(r"[?&]page=\d+", d.url or "", re.I):
            url_bonus -= 2
        return (url_bonus + job_hits + year_hits, d.id)

    hub_ranked = sorted(hub_rows, key=_hub_quality, reverse=True)
    # Diversify hubs by host — avoid 8 copies of botanica.md listing chrome
    hub_rows = []
    hosts: dict[str, int] = {}
    for d in hub_ranked:
        host = (urlparse(d.url or "").netloc or "unknown").lower()
        if hosts.get(host, 0) >= 2:
            continue
        hosts[host] = hosts.get(host, 0) + 1
        hub_rows.append(d)
        if len(hub_rows) >= 6:
            break
    other_rows = (
        db.query(Document)
        .filter(
            (
                Document.title.ilike("%concurs%")
                | Document.title.ilike("%anunț%func%")
                | Document.title.ilike("%anunt%func%")
                | Document.title.ilike("%funcți%vacant%")
                | Document.title.ilike("%functii%vacant%")
                | Document.title.ilike("%funcţie%vacant%")
                | Document.title.ilike("%funcție%vacant%")
                | Document.title.ilike("%ocuparea%func%")
                | Document.title.ilike("%posturi%vacant%")
                | Document.url.ilike("%/concurs%")
            )
            & noise
        )
        .order_by(Document.id.desc())
        .limit(limit * 6)
        .all()
    )
    seen_ids: set[int] = set()
    rows: list[Document] = []
    for d in list(hub_rows) + list(other_rows):
        if d.id in seen_ids:
            continue
        seen_ids.add(d.id)
        rows.append(d)

    out: list[RetrievedChunk] = []
    for d in rows:
        title = (d.title or "").lower()
        content = d.content or ""
        url_l = (d.url or "").lower()
        is_hub = bool(
            "posturi-vacante" in url_l
            or "functii-vacante" in url_l
            or title.strip()
            in (
                "posturi vacante",
                "funcții vacante",
                "functii vacante",
                "funcţii vacante",
                "locuri vacante",
            )
        )
        blob = f"{title}\n{content[:1200]}"
        if re.search(
            r"vacan[țt]e?[ai]?\s+de\s+var|gr[ăa]dini[țt]|copiilor\s+[îi]n\s+vacan",
            blob,
            re.I,
        ):
            continue
        if is_hub:
            if not re.search(
                r"anun[țt].{0,100}concurs|specialist|depune.{0,20}dosar|"
                r"func[tț](?:iei|ia)\s+public|ocuparea\s+func|"
                r"\d{2}\.\d{2}\.2026",
                content,
                re.I,
            ):
                continue
        # Finished / winner notices are not open vacancies
        if not is_hub and re.search(
            r"\b(?:[îi]nving[aă]tor|desemnarea\s+[îi]nving|c[aâ][sș]tig[aă]tor|"
            r"a\s+avut\s+loc\s+etapa)\b",
            title,
            re.I,
        ):
            continue
        if re.search(
            r"s-a\s+desf[ăa][sș]urat|rezultatele\s+finale\s+vor\s+fi",
            content,
            re.I,
        ) and not re.search(
            r"depune(?:rea)?\s+dosar|până\s+(?:în|la)\s+data|se\s+prelung",
            content,
            re.I,
        ):
            continue
        chunk = (
            db.query(Chunk)
            .filter_by(document_id=d.id)
            .order_by(Chunk.id.asc())
            .first()
        )
        # Hub pages: prefer full document preview so all listings stay visible
        text = (content if is_hub else (chunk.content if chunk else content)) or ""
        preview_n = 3200 if is_hub else 2000
        out.append(
            RetrievedChunk(
                chunk_id=chunk.id if chunk else -d.id,
                document_id=d.id,
                document_title=d.title,
                document_url=d.url,
                content=text[:preview_n],
                page=chunk.page if chunk else None,
                section=chunk.section if chunk else None,
                dense_score=0.72 if is_hub else 0.62,
                lexical_score=0.98 if is_hub else 0.9,
                rerank_score=0.78 if is_hub else 0.58,
            )
        )
        if len(out) >= limit:
            break
    return out


def _lexical_topic_hits(
    db: Session, terms: list[str], *, limit: int = 6
) -> list[RetrievedChunk]:
    """SQL title/content rescue for distinctive topic terms (any intent)."""
    clean = [t.strip() for t in terms if t and len(t.strip()) >= 4][:5]
    if not clean:
        return []
    from sqlalchemy import or_

    clauses = []
    for t in clean:
        like = f"%{t}%"
        clauses.append(Document.title.ilike(like))
        clauses.append(Document.url.ilike(like))
    rows = (
        db.query(Document)
        .filter(or_(*clauses))
        .order_by(Document.id.desc())
        .limit(limit * 3)
        .all()
    )
    out: list[RetrievedChunk] = []
    folded_terms = {fold(t) for t in clean}
    for d in rows:
        blob_f = fold(f"{d.title or ''} {(d.content or '')[:800]}")
        if not any(t in blob_f for t in folded_terms):
            continue
        chunk = (
            db.query(Chunk)
            .filter_by(document_id=d.id)
            .order_by(Chunk.id.asc())
            .first()
        )
        text = (chunk.content if chunk else d.content) or ""
        out.append(
            RetrievedChunk(
                chunk_id=chunk.id if chunk else -d.id,
                document_id=d.id,
                document_title=d.title,
                document_url=d.url,
                content=text[:2000],
                page=chunk.page if chunk else None,
                section=chunk.section if chunk else None,
                dense_score=0.55,
                lexical_score=0.85,
                rerank_score=0.5,
            )
        )
        if len(out) >= limit:
            break
    return out


def _merge_hits(
    primary: list[RetrievedChunk],
    secondary: list[RetrievedChunk],
    *,
    limit: int,
) -> list[RetrievedChunk]:
    seen: set[int] = set()
    merged: list[RetrievedChunk] = []
    for h in primary + secondary:
        if h.document_id in seen:
            continue
        seen.add(h.document_id)
        merged.append(h)
        if len(merged) >= limit:
            break
    return merged


def tool_filter_noise_docs(
    hits: list[RetrievedChunk], *, intent: str
) -> dict[str, Any]:
    if not hits:
        return {"summary": "Fără hit-uri", "hits": hits, "kept": 0}

    if intent == "concurs":
        cleaned = []
        for h in hits:
            blob = f"{h.document_title or ''}\n{h.content or ''}"
            if re.search(
                r"vacan[țt]e?[ai]?\s+de\s+var|gr[ăa]dini[țt]|copiilor\s+[îi]n\s+vacan",
                blob,
                re.I,
            ) and not re.search(
                r"funcț(?:iei|ia|ii)\s+public|ocuparea\s+func|anun[țt].{0,40}concurs",
                blob,
                re.I,
            ):
                continue
            cleaned.append(h)
        return {
            "summary": f"Păstrate {len(cleaned)} (fără vacanță școlară)",
            "hits": cleaned or hits,
            "kept": len(cleaned) or len(hits),
            "dropped": max(0, len(hits) - len(cleaned)),
        }

    if intent != "contact":
        return {"summary": "Fără filtrare zgomot", "hits": hits, "kept": len(hits)}

    def is_noise(h: RetrievedChunk) -> bool:
        blob = f"{h.document_title or ''} {h.content or ''}"
        if _VACANCY_RE.search(blob):
            return True
        # prefer pages that look like contacts
        return False

    def contact_score(h: RetrievedChunk) -> float:
        blob = f"{h.document_title or ''} {h.content or ''}".lower()
        score = float(h.rerank_score or h.score or 0)
        if "contact" in blob or "telefon" in blob or "@" in blob:
            score += 0.35
        if _VACANCY_RE.search(blob):
            score -= 0.5
        return score

    cleaned = [h for h in hits if not is_noise(h)]
    if not cleaned:
        # keep original but re-rank contact-ish first
        cleaned = sorted(hits, key=contact_score, reverse=True)
    else:
        cleaned = sorted(cleaned, key=contact_score, reverse=True)
    dropped = len(hits) - len(cleaned) if cleaned != hits else sum(
        1 for h in hits if is_noise(h)
    )
    return {
        "summary": f"Păstrate {len(cleaned)} (eliminate {dropped} anunțuri/concurs)",
        "hits": cleaned,
        "kept": len(cleaned),
        "dropped": dropped,
    }


def tool_filter_by_year(
    hits: list[RetrievedChunk], *, wants_current: bool, intent: str = "general"
) -> dict[str, Any]:
    year = _now_year()
    if not wants_current or not hits:
        return {"summary": "Fără filtru temporal", "hits": hits, "kept": len(hits)}

    def year_of(h: RetrievedChunk) -> int | None:
        return _chunk_year(h)

    dated_fresh = [h for h in hits if (year_of(h) or 0) >= year]
    dated_recent = [h for h in hits if (year_of(h) or 0) >= year - 1]
    undated = [h for h in hits if year_of(h) is None]

    # Concurs: prefer dated fresh; allow undated anunț titles; drop ancient dated
    if intent == "concurs":
        def looks_open(h: RetrievedChunk) -> bool:
            blob = f"{h.document_title or ''}\n{h.content or ''}"
            if re.search(
                r"s-a\s+desf[ăa][sș]urat|rezultatele\s+finale|"
                r"a\s+fost\s+(?:desfăşurat|desfasurat|încheiat)",
                blob,
                re.I,
            ):
                # finished write-up unless it still invites applications
                if not re.search(r"depune(?:rea)?\s+dosar|până\s+(?:în|la)\s+data", blob, re.I):
                    return False
            return bool(
                re.search(
                    r"anun[țt]|concurs|vacant|funcț|functie|dosar",
                    blob,
                    re.I,
                )
            )

        preferred = [h for h in dated_fresh if looks_open(h)]
        if not preferred:
            preferred = [h for h in dated_recent if looks_open(h)]
        if not preferred:
            preferred = [h for h in undated if looks_open(h)]
        if preferred:
            return {
                "summary": f"Păstrate {len(preferred)} anunțuri curente/relevante",
                "hits": preferred,
                "kept": len(preferred),
                "dropped": len(hits) - len(preferred),
            }

    if dated_fresh:
        return {
            "summary": f"Păstrate {len(dated_fresh)} surse din {year}+",
            "hits": dated_fresh,
            "kept": len(dated_fresh),
            "dropped": len(hits) - len(dated_fresh),
        }
    # Do NOT treat undated as current-year — that promoted finished contests
    if dated_recent:
        return {
            "summary": f"Nicio sursă {year}; păstrăm {year - 1}+ ({len(dated_recent)})",
            "hits": dated_recent,
            "kept": len(dated_recent),
            "historical_only": True,
        }
    return {
        "summary": f"Fără an în text; păstrăm {len(hits)} (nedatate)",
        "hits": hits,
        "kept": len(hits),
        "undated": True,
    }


def tool_verify(
    hits: list[RetrievedChunk],
    question: str,
    *,
    answer_mode: str = "fact",
    wants_list: bool = False,
) -> dict[str, Any]:
    gate, usable = verify_evidence(
        hits,
        question=question,
        answer_mode=answer_mode,
        wants_list=wants_list,
    )
    return {
        "summary": f"Status={gate}; usable={len(usable)}",
        "gate": gate,
        "usable": usable,
    }


def tool_extract_contact_fields(
    usable: list[RetrievedChunk], *, institution: str | None
) -> dict[str, Any]:
    blob = "\n".join(
        f"{h.document_title or ''}\n{h.content or ''}" for h in usable[:8]
    )
    phones = list(dict.fromkeys(_PHONE_RE.findall(blob)))[:5]
    emails = list(dict.fromkeys(e.lower() for e in _EMAIL_RE.findall(blob)))[:5]
    addrs = list(dict.fromkeys(a.strip() for a in _ADDR_RE.findall(blob)))[:3]

    # Prefer institution-matching email when known
    if institution and institution in INSTITUTION_CONTACTS:
        want = INSTITUTION_CONTACTS[institution]["email"].lower()
        if want in emails:
            emails = [want] + [e for e in emails if e != want]

    summary_bits = []
    if phones:
        summary_bits.append(f"{len(phones)} tel")
    if emails:
        summary_bits.append(f"{len(emails)} email")
    if addrs:
        summary_bits.append(f"{len(addrs)} adr")
    return {
        "summary": ", ".join(summary_bits) if summary_bits else "Niciun câmp extras",
        "phones": phones,
        "emails": emails,
        "addresses": addrs,
    }


def tool_lookup_known_contacts(institution: str | None) -> dict[str, Any]:
    if not institution or institution not in INSTITUTION_CONTACTS:
        return {"summary": "Fără contact cunoscut pentru instituție", "contact": None}
    c = INSTITUTION_CONTACTS[institution]
    return {
        "summary": f"{c['name']}: {c['phone']}",
        "contact": c,
    }


def tool_classify_sources(usable: list[RetrievedChunk]) -> dict[str, Any]:
    meta = []
    for h in usable:
        t = classify_doc_type(h.document_title or "", h.document_url, h.content or "")
        meta.append(
            {
                "document": h.document_title,
                "url": h.document_url,
                "type": t,
                "page": h.page,
                "year": _chunk_year(h),
            }
        )
    types = sorted({m["type"] for m in meta})
    return {
        "summary": "Tipuri: " + (", ".join(types) if types else "—"),
        "sources": meta,
    }


def tool_detect_conflicts(
    usable: list[RetrievedChunk], question: str
) -> dict[str, Any]:
    if not question_about_deadline(question) or len(usable) < 2:
        return {"summary": "Niciun conflict detectat", "conflicts": []}
    by_doc: dict[str, set[int]] = {}
    quotes: dict[str, str] = {}
    for h in usable:
        days = _deadline_mentions(h.content or "")
        if not days:
            continue
        key = h.document_title or h.document_url or str(h.document_id)
        by_doc.setdefault(key, set()).update(days)
        quotes[key] = (h.content or "")[:280]
        quotes[key + "::url"] = h.document_url or ""
        quotes[key + "::page"] = str(h.page or "")
    conflicts = []
    keys = list(by_doc.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if by_doc[a] != by_doc[b]:
                conflicts.append(
                    {
                        "left": {
                            "document": a,
                            "days": sorted(by_doc[a]),
                            "quote": quotes.get(a, ""),
                            "url": quotes.get(a + "::url"),
                            "page": quotes.get(a + "::page") or None,
                        },
                        "right": {
                            "document": b,
                            "days": sorted(by_doc[b]),
                            "quote": quotes.get(b, ""),
                            "url": quotes.get(b + "::url"),
                            "page": quotes.get(b + "::page") or None,
                        },
                    }
                )
    return {
        "summary": (
            f"{len(conflicts)} conflict(e) de termene"
            if conflicts
            else "Niciun conflict de termene"
        ),
        "conflicts": conflicts,
    }


def tool_fetch_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL invalid")
    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 CivicAI-Tool"})
    ctype = (resp.headers.get("content-type") or "").lower()
    title, text = url, ""
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(resp.content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:8])
            title = url.rsplit("/", 1)[-1]
        except Exception:  # noqa: BLE001
            text = f"(PDF binary, {len(resp.content)} bytes — text neextractabil)"
    else:
        title, text, _ = extract_html(str(resp.url), resp.content)
    text = (text or "").strip()[:3500]
    return {
        "summary": f"Extras {len(text)} caractere din {urlparse(url).netloc}",
        "url": str(resp.url),
        "title": title,
        "excerpt": text[:600],
        "text": text,
        "status_code": resp.status_code,
    }


def tool_resolve_contact(
    db: Session,
    question: str,
    *,
    institution: str | None = None,
    known: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if known:
        return {
            "summary": f"Contact: {known.get('name')}",
            "label": known.get("name") or "Contact",
            "url": known.get("url") or "https://www.chisinau.md/",
            "contact": " · ".join(
                x
                for x in (
                    known.get("address"),
                    known.get("phone"),
                    known.get("email"),
                )
                if x
            ),
        }
    if institution and institution in INSTITUTION_CONTACTS:
        c = INSTITUTION_CONTACTS[institution]
        return {
            "summary": f"Contact: {c['name']}",
            "label": c["name"],
            "url": c["url"],
            "contact": f"{c['address']} · {c['phone']} · {c['email']}",
        }

    links = db.query(TopicLink).all()
    q = (question or "").lower()
    best = None
    best_score = 0.0
    for t in links:
        score = _token_overlap(q, f"{t.topic_ro} {t.topic_ru}")
        if score > best_score:
            best_score = score
            best = t
    if not best or best_score < 0.08:
        if re.search(r"autoriz|urban|construir|dgaurf", q, re.I):
            return {
                "summary": "Contact DGAURF",
                "label": "DGAURF — Cadrul normativ",
                "url": "https://dgaurf.md/ro/regulatory",
                "contact": "dgaurf@cmc.md · +373 68 675 889",
            }
        return {
            "summary": "Ghișeul Unic Primărie",
            "label": "Ghișeul Unic Primăria Chișinău",
            "url": "https://www.chisinau.md/",
            "contact": "+373 22 20 15 05 · primaria@pmc.md",
        }
    return {
        "summary": f"Contact: {best.contact_label or best.topic_ro}",
        "label": best.contact_label or best.topic_ro,
        "url": best.url,
        "contact": best.contact_value,
    }


def tool_estimate_confidence(
    gate: str,
    usable: list[RetrievedChunk],
    question: str,
    conflicts: list,
    *,
    known_contact: dict | None = None,
    intent: str = "general",
) -> dict[str, Any]:
    if intent == "contact" and known_contact:
        return {
            "summary": "Încredere high (contact oficial)",
            "level": "high",
            "score": 0.92,
        }
    if gate == "missing" or not usable:
        return {"summary": "Încredere scăzută (lipsă evidență)", "level": "low", "score": 0.15}
    ov = max(
        (
            _token_overlap(question, f"{h.document_title} {h.content}")
            for h in usable
        ),
        default=0.0,
    )
    rr = max((float(h.rerank_score or 0) for h in usable), default=0.0)
    score = min(0.95, 0.25 + ov * 0.45 + rr * 0.4)
    if conflicts:
        score = min(score, 0.55)
        level = "medium"
    elif score >= 0.7:
        level = "high"
    elif score >= 0.4:
        level = "medium"
    else:
        level = "low"
    return {
        "summary": f"Încredere {level} ({score:.0%})",
        "level": level,
        "score": round(score, 3),
    }


def tool_corpus_health(db: Session) -> dict[str, Any]:
    docs = db.query(Document).count()
    chunks = db.query(Chunk).count()
    return {
        "summary": f"{docs} documente · {chunks} chunk-uri",
        "documents": docs,
        "chunks": chunks,
        "target_min": 5000,
        "ready_for_demo": docs >= 100,
    }


def tool_read_document(db: Session, *, document_id: int | None = None, url: str | None = None) -> dict[str, Any]:
    doc: Document | None = None
    if document_id:
        doc = db.get(Document, document_id)
    elif url:
        doc = db.query(Document).filter(Document.url == url).first()
        if not doc:
            doc = db.query(Document).filter(Document.url.ilike(f"%{url[-80:]}")).first()
    if not doc:
        return {"summary": "Document negăsit", "found": False, "optional": True}
    preview = (doc.content or "")[:2500]
    return {
        "summary": f"Citesc «{doc.title[:60]}» ({len(doc.content or '')} chars)",
        "found": True,
        "id": doc.id,
        "title": doc.title,
        "url": doc.url,
        "mime_type": doc.mime_type,
        "preview": preview,
        "optional": True,
    }


def tool_read_document_chunks(
    db: Session, *, document_id: int, limit: int = 8
) -> dict[str, Any]:
    rows = (
        db.query(Chunk)
        .filter_by(document_id=document_id)
        .order_by(Chunk.id.asc())
        .limit(limit)
        .all()
    )
    return {
        "summary": f"{len(rows)} pasaje din doc #{document_id}",
        "chunks": [
            {
                "id": c.id,
                "page": c.page,
                "section": c.section,
                "text": (c.content or "")[:500],
            }
            for c in rows
        ],
        "optional": True,
    }


def tool_find_document_by_url(db: Session, url: str) -> dict[str, Any]:
    doc = db.query(Document).filter(Document.url == url).first()
    if not doc and url:
        host = urlparse(url).netloc
        doc = (
            db.query(Document)
            .filter(Document.url.ilike(f"%{host}%"))
            .order_by(Document.id.desc())
            .first()
        )
    if not doc:
        return {"summary": "Niciun document pe URL", "found": False, "optional": True}
    return {
        "summary": f"Găsit: {doc.title[:50]}",
        "found": True,
        "id": doc.id,
        "title": doc.title,
        "url": doc.url,
        "optional": True,
    }


def tool_refresh_document(db: Session, *, url: str) -> dict[str, Any]:
    """Re-fetch URL and re-index (update corpus)."""
    from backend.crawler.fetcher import Fetcher
    from backend.crawler.html_parser import extract_html
    from backend.crawler.ingest import ensure_source, ingest_text_document, mark_source_crawled
    from backend.crawler.pdf import extract_pdf

    fetched = Fetcher().fetch(url)
    if not fetched or fetched.status >= 400:
        return {"summary": "Refresh eșuat — fetch", "ok": False, "optional": True}
    ctype = fetched.content_type or ""
    text = ""
    pages = None
    title = url
    mime = ctype or "text/plain"
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        text, pages = extract_pdf(fetched.body)
        mime = "application/pdf"
    else:
        title, text, _ = extract_html(fetched.final_url, fetched.body)
        mime = "text/html"
    if len((text or "").strip()) < 40:
        return {"summary": "Refresh eșuat — conținut scurt", "ok": False, "optional": True}
    src = ensure_source(db, url=fetched.final_url, name=urlparse(fetched.final_url).netloc)
    doc = ingest_text_document(
        db,
        source=src,
        title=(title or url)[:512],
        url=fetched.final_url,
        text=text,
        mime_type=mime,
        pages=pages,
    )
    mark_source_crawled(db, src)
    db.commit()
    if not doc:
        return {"summary": "Refresh eșuat — ingest", "ok": False, "optional": True}
    return {
        "summary": f"Actualizat «{doc.title[:50]}»",
        "ok": True,
        "id": doc.id,
        "url": doc.url,
        "optional": True,
    }


def tool_list_recent_documents(db: Session, *, limit: int = 8) -> dict[str, Any]:
    rows = db.query(Document).order_by(Document.id.desc()).limit(limit).all()
    return {
        "summary": f"{len(rows)} documente recente",
        "items": [
            {"id": d.id, "title": d.title, "url": d.url, "mime": d.mime_type}
            for d in rows
        ],
        "optional": True,
    }


_DATE_RE = re.compile(
    r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|"
    r"septembrie|octombrie|noiembrie|decembrie)\s+\d{4})\b",
    re.I,
)
_DEADLINE_SPAN_RE = re.compile(
    r"(\d+\s*(?:zile?\s+lucrătoare|zile|zile\s+calendaristice|working\s+days?|"
    r"дней|рабочих\s+дней))",
    re.I,
)


def tool_extract_dates_deadlines(hits: list[RetrievedChunk]) -> dict[str, Any]:
    dates: list[str] = []
    deadlines: list[str] = []
    for h in hits[:6]:
        blob = f"{h.document_title or ''}\n{h.content or ''}"
        for m in _DATE_RE.finditer(blob):
            dates.append(m.group(1))
        for m in _DEADLINE_SPAN_RE.finditer(blob):
            deadlines.append(m.group(1))
    dates = list(dict.fromkeys(dates))[:12]
    deadlines = list(dict.fromkeys(deadlines))[:8]
    return {
        "summary": f"{len(dates)} date · {len(deadlines)} termene",
        "dates": dates,
        "deadlines": deadlines,
        "optional": True,
    }


def tool_lookup_topic_link(db: Session, question: str) -> dict[str, Any]:
    q = (question or "").lower()
    rows = db.query(TopicLink).all()
    best = None
    best_score = 0
    for row in rows:
        score = 0
        for tok in re.findall(r"[a-zăâîșț]{4,}", (row.topic_ro or "").lower()):
            if tok in q:
                score += 2
        for tok in re.findall(r"[a-zа-яё]{4,}", (row.topic_ru or "").lower()):
            if tok in q:
                score += 2
        if score > best_score:
            best_score = score
            best = row
    if not best or best_score < 2:
        return {"summary": "Nicio temă mapată", "found": False, "optional": True}
    return {
        "summary": f"Temă: {best.topic_ro}",
        "found": True,
        "topic_ro": best.topic_ro,
        "topic_ru": best.topic_ru,
        "url": best.url,
        "contact_label": best.contact_label,
        "contact_value": best.contact_value,
        "optional": True,
    }


def tool_search_exact_phrase(
    db: Session, phrase: str, *, limit: int = 5
) -> dict[str, Any]:
    phrase = (phrase or "").strip()
    if len(phrase) < 4:
        return {"summary": "Frază prea scurtă", "hits": [], "optional": True}
    like = f"%{phrase}%"
    rows = (
        db.query(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .filter(Chunk.content.ilike(like))
        .limit(limit)
        .all()
    )
    return {
        "summary": f"{len(rows)} potriviri exacte",
        "hits": [
            {
                "document_id": d.id,
                "title": d.title,
                "url": d.url,
                "snippet": (c.content or "")[:280],
            }
            for c, d in rows
        ],
        "optional": True,
    }


def tool_get_document_changes(db: Session, *, document_id: int, limit: int = 5) -> dict[str, Any]:
    rows = (
        db.query(DocumentChange)
        .filter_by(document_id=document_id)
        .order_by(DocumentChange.detected_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "summary": f"{len(rows)} schimbări pe doc #{document_id}",
        "changes": [
            {
                "old": ch.old_hash[:10],
                "new": ch.new_hash[:10],
                "diff": (ch.diff or "")[:200],
                "at": ch.detected_at.isoformat() if ch.detected_at else None,
            }
            for ch in rows
        ],
        "optional": True,
    }


def tool_source_coverage(db: Session, *, limit: int = 10) -> dict[str, Any]:
    rows = db.query(Source).order_by(Source.id.desc()).limit(40).all()
    items = []
    for s in rows:
        n = db.query(Document).filter_by(source_id=s.id).count()
        items.append({"name": s.name, "url": s.url, "documents": n, "priority": s.priority})
    items.sort(key=lambda x: -x["documents"])
    items = items[:limit]
    return {
        "summary": f"Top {len(items)} surse după volum",
        "sources": items,
        "optional": True,
    }


def tool_read_multi_documents(
    db: Session, document_ids: list[int], *, preview_chars: int = 1800
) -> dict[str, Any]:
    """Read several full documents so the answer can synthesize across sources."""
    ids = list(dict.fromkeys(int(i) for i in document_ids if i))[:8]
    docs_out: list[dict[str, Any]] = []
    for did in ids:
        doc = db.get(Document, did)
        if not doc:
            continue
        docs_out.append(
            {
                "id": doc.id,
                "title": doc.title,
                "url": doc.url,
                "preview": (doc.content or "")[:preview_chars],
                "chars": len(doc.content or ""),
            }
        )
    return {
        "summary": f"Citite {len(docs_out)} documente",
        "documents": docs_out,
        "optional": True,
    }


def tool_expand_related_chunks(
    db: Session,
    hits: list[RetrievedChunk],
    *,
    per_doc: int = 3,
    max_extra: int = 12,
) -> dict[str, Any]:
    """Pull more chunks from the same documents already in evidence."""
    if not hits:
        return {"summary": "Nimic de extins", "hits": [], "optional": True}
    seen_chunk = {h.chunk_id for h in hits}
    by_doc: dict[int, list[RetrievedChunk]] = {}
    for h in hits:
        by_doc.setdefault(h.document_id, []).append(h)
    extra: list[RetrievedChunk] = []
    for doc_id in list(by_doc.keys())[:8]:
        rows = (
            db.query(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .filter(Chunk.document_id == doc_id)
            .order_by(Chunk.id.asc())
            .limit(per_doc + 2)
            .all()
        )
        for c, d in rows:
            if c.id in seen_chunk:
                continue
            extra.append(
                RetrievedChunk(
                    chunk_id=c.id,
                    document_id=d.id,
                    document_title=d.title,
                    document_url=d.url,
                    content=c.content or "",
                    page=c.page,
                    section=c.section,
                    dense_score=0.5,
                    lexical_score=0.5,
                    rerank_score=0.45,
                )
            )
            seen_chunk.add(c.id)
            if len(extra) >= max_extra:
                break
        if len(extra) >= max_extra:
            break
    return {
        "summary": f"+{len(extra)} pasaje din aceleași documente",
        "hits": extra,
        "optional": True,
    }


def tool_broaden_corpus_search(
    db: Session,
    question: str,
    existing: list[RetrievedChunk],
    *,
    intent: str,
    top_k: int = 10,
    topic_terms: list[str] | None = None,
) -> dict[str, Any]:
    """Second-pass hybrid search with alternate phrasings; union into evidence pool."""
    alts = _heuristic_queries(question, intent=intent, institution=None)
    if intent == "concurs":
        alts = [
            "anunț concurs ocuparea funcției publice",
            "pretura concurs specialist dosar",
            "AVIZ CONCURS etapă",
            "funcții publice vacante primărie",
            *alts,
        ]
    merged = list(existing)
    added = 0
    for q in alts[:6]:
        try:
            more = HybridRetriever(db).search(q, top_k=max(4, top_k // 2))
        except Exception:  # noqa: BLE001
            continue
        before = len(merged)
        merged = _merge_hits(merged, more, limit=top_k + 10)
        added += max(0, len(merged) - before)
    if intent == "concurs":
        merged = _merge_hits(_lexical_concurs_hits(db, limit=12), merged, limit=top_k + 12)
    if topic_terms:
        merged = _merge_hits(
            _lexical_topic_hits(db, topic_terms, limit=8), merged, limit=top_k + 12
        )
    return {
        "summary": f"Extins: {len(merged)} pasaje (+{added} noi)",
        "hits": merged,
        "added": added,
        "optional": True,
    }


_SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("autorizație", "autorizatie", "permis", "e-permis", "construire", "building permit"),
    ("contact", "telefon", "email", "adresă", "adresa", "phone"),
    ("pretura", "sector", "botanica", "buiucani", "ciocana", "râșcani", "rascani"),
    ("concurs", "funcție vacantă", "functii vacante", "funcții publice", "vacancy", "angajare", "aplic"),
    ("termen", "zile lucrătoare", "deadline", "срок"),
    ("petiție", "petitie", "cerere", "sesizare"),
    ("dgaurf", "urbanism", "arhitectură", "arhitectura"),
]


def _heuristic_queries(
    question: str, *, intent: str, institution: str | None
) -> list[str]:
    q = (question or "").strip()
    out: list[str] = []
    low = q.lower()
    for group in _SYNONYM_GROUPS:
        if any(g in low for g in group):
            # pick other terms from same group
            extras = [g for g in group if g not in low][:3]
            if extras:
                out.append(" ".join(extras[:2]) + (" " + (institution or "")).strip())
    if institution and institution in INSTITUTION_CONTACTS:
        name = INSTITUTION_CONTACTS[institution]["name"]
        if intent == "contact":
            out.append(f"{name} telefon email adresă")
            out.append(f"contact {institution} pretura")
        else:
            out.append(name)
    # keyword skeleton: drop short stopwords
    stops = {
        "care", "sunt", "este", "pentru", "despre", "the", "and", "what", "where",
        "how", "are", "для", "что", "как", "ale", "din", "cu", "unei", "unui",
    }
    toks = [
        w
        for w in re.findall(r"[a-zăâîșțёа-я0-9]{3,}", low)
        if w not in stops
    ]
    if toks:
        out.append(" ".join(toks[:6]))
    # dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.strip().lower()
        if key and key != q.lower() and key not in seen:
            seen.add(key)
            uniq.append(item.strip())
    return uniq[:4]


def tool_expand_search_queries(
    question: str,
    *,
    intent: str,
    institution: str | None,
    use_llm: bool = True,
) -> dict[str, Any]:
    queries = _heuristic_queries(question, intent=intent, institution=institution)
    source = "heuristic"
    if use_llm:
        try:
            from backend.ai.llm import get_llm_service

            llm_q = get_llm_service().expand_search_queries(question, max_queries=4)
            for q in llm_q:
                if q.lower() not in {x.lower() for x in queries}:
                    queries.append(q)
            if llm_q:
                source = "heuristic+llm"
        except Exception:  # noqa: BLE001
            pass
    queries = queries[:5]
    return {
        "summary": f"{len(queries)} query-uri ({source})",
        "queries": queries,
        "source": source,
        "optional": True,
    }


def tool_research_corpus(
    db: Session,
    queries: list[str],
    existing: list[RetrievedChunk],
    *,
    top_k: int = 4,
) -> dict[str, Any]:
    if not queries:
        return {
            "summary": "Fără query-uri — skip",
            "hits": existing,
            "added": 0,
            "optional": True,
        }
    seen_ids = {(h.document_id, h.page, (h.content or "")[:80]) for h in existing}
    merged = list(existing)
    added = 0
    retriever = HybridRetriever(db)
    for q in queries[:4]:
        try:
            hits = retriever.search(q, top_k=top_k)
        except Exception:  # noqa: BLE001
            continue
        for h in hits:
            key = (h.document_id, h.page, (h.content or "")[:80])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            merged.append(h)
            added += 1
    return {
        "summary": f"+{added} pasaje din {len(queries)} query-uri",
        "hits": merged,
        "added": added,
        "queries_used": queries,
        "optional": True,
    }


def _needs_optional_research(
    gate: str,
    usable: list[RetrievedChunk],
    intent: str,
    question: str = "",
    *,
    wants_list: bool = False,
    wants_current: bool = False,
    answer_mode: str = "fact",
) -> bool:
    q = (question or "").lower()
    list_q = wants_list or answer_mode == "list" or bool(
        re.search(
            r"\b(exist[ăa]|deschis|list[ăa]|care\s+sunt|ce\s+concurs|toate|"
            r"câte|cate|открыт|есть\s+ли|pot\s+(?:să\s+)?aplic)\b",
            q,
            re.I,
        )
    )
    if intent == "contact" and usable:
        blob = " ".join(
            f"{h.document_title or ''} {h.content or ''}" for h in usable[:3]
        ).lower()
        if any(k in blob for k in ("telefon", "email", "@", "contact", "str.")):
            return False
    # Listing / inventory questions: always broaden for coverage
    if list_q:
        return True
    # "Now/current" but no this-year docs → research even if gate looks supported
    if wants_current and usable:
        year = _now_year()
        if not any((_chunk_year(h) or 0) >= year for h in usable):
            return True
    if intent == "concurs" and gate == "supported" and usable and not list_q:
        # still research if only one doc — listing jobs often need several anunțuri
        if len({h.document_id for h in usable}) < 2:
            return True
        return False
    if gate == "supported" and len(usable) >= 2 and not list_q and not wants_current:
        avg_len = sum(len(h.content or "") for h in usable) / max(1, len(usable))
        if avg_len >= 180:
            return False
    if gate == "missing":
        return True
    if len(usable) < 1:
        return True
    if wants_current and gate == "supported" and len({h.document_id for h in usable}) < 2:
        return True
    return False


def _format_contact_answer(c: dict[str, str], lang: str = "ro") -> str:
    if lang == "ru":
        return (
            f"**{c['name']}**\n\n"
            f"- Адрес: {c['address']}\n"
            f"- Телефон: {c['phone']}\n"
            f"- Email: {c['email']}\n"
            f"- Сайт: {c['url']}"
        )
    if lang == "en":
        return (
            f"**{c['name']}**\n\n"
            f"- Address: {c['address']}\n"
            f"- Phone: {c['phone']}\n"
            f"- Email: {c['email']}\n"
            f"- Website: {c['url']}"
        )
    return (
        f"**{c['name']}**\n\n"
        f"- Adresă: {c['address']}\n"
        f"- Telefon: {c['phone']}\n"
        f"- Email: {c['email']}\n"
        f"- Site: {c['url']}"
    )


def run_agent_pipeline(
    db: Session,
    question: str,
    *,
    top_k: int = 5,
    ui_language: str | None = None,
) -> Iterator[ToolEvent | AgentState]:
    """Yield ToolEvent for UI, then final AgentState."""
    state = AgentState(question=question, ui_language=ui_language)

    # 1 analyze
    yield _start_event("analyze_question")
    analyzed, ev = run_tool(
        "analyze_question",
        lambda: tool_analyze_question(question, ui_language=ui_language),
    )
    yield ev
    state.tools_run.append("analyze_question")
    if analyzed:
        state.language = analyzed["language"]
        state.language_meta = analyzed.get("language_meta") or {}
        state.wants_current = analyzed["wants_current"]
        state.wants_list = bool(analyzed.get("wants_list"))
        state.answer_mode = analyzed.get("answer_mode") or "fact"
        state.topic_terms = list(analyzed.get("topic_terms") or [])
        state.urls_in_question = analyzed.get("urls") or []
        state.intent = analyzed.get("intent") or "general"

    # 2 detect institution
    yield _start_event("detect_institution")
    inst, ev = run_tool(
        "detect_institution", lambda: tool_detect_institution(question)
    )
    yield ev
    state.tools_run.append("detect_institution")
    if inst:
        state.institution = inst.get("institution")

    # 3 build search query
    yield _start_event("build_search_query")
    built, ev = run_tool(
        "build_search_query",
        lambda: tool_build_search_query(
            question, intent=state.intent, institution=state.institution
        ),
    )
    yield ev
    state.tools_run.append("build_search_query")
    state.search_query = (built or {}).get("query") or question

    # 4 fetch URL if present (optional)
    if state.urls_in_question:
        yield _start_event("fetch_url", state.urls_in_question[0][:80])
        fetched, ev = run_tool(
            "fetch_url", lambda: tool_fetch_url(state.urls_in_question[0])
        )
        yield ev
        state.tools_run.append("fetch_url")
        if fetched:
            state.fetched.append(fetched)

    # 5 search
    yield _start_event("search_corpus")
    searched, ev = run_tool(
        "search_corpus",
        lambda: tool_search_corpus(
            db,
            state.search_query,
            top_k=top_k,
            intent=state.intent,
            answer_mode=state.answer_mode,
            topic_terms=state.topic_terms,
        ),
    )
    yield ev
    state.tools_run.append("search_corpus")
    hits = (searched or {}).get("hits") or []

    # 6 noise filter
    yield _start_event("filter_noise_docs")
    denoised, ev = run_tool(
        "filter_noise_docs",
        lambda: tool_filter_noise_docs(hits, intent=state.intent),
    )
    yield ev
    state.tools_run.append("filter_noise_docs")
    hits = (denoised or {}).get("hits") or hits

    # 7 year filter
    yield _start_event("filter_by_year")
    filtered, ev = run_tool(
        "filter_by_year",
        lambda: tool_filter_by_year(
            hits, wants_current=state.wants_current, intent=state.intent
        ),
    )
    yield ev
    state.tools_run.append("filter_by_year")
    hits = (filtered or {}).get("hits") or hits
    state.hits = hits

    # 8 verify
    yield _start_event("verify_evidence")
    verified, ev = run_tool(
        "verify_evidence",
        lambda: tool_verify(
            hits,
            question,
            answer_mode=state.answer_mode,
            wants_list=state.wants_list,
        ),
    )
    yield ev
    state.tools_run.append("verify_evidence")
    state.gate = (verified or {}).get("gate") or "missing"
    state.usable = (verified or {}).get("usable") or []
    best_gate, best_usable = state.gate, list(state.usable)

    if state.fetched and state.gate == "missing":
        state.gate = "supported"
        best_gate, best_usable = state.gate, list(state.usable)

    # 9–10 optional research / broaden when evidence is weak OR listing question
    if _needs_optional_research(
        state.gate,
        state.usable,
        state.intent,
        question,
        wants_list=state.wants_list,
        wants_current=state.wants_current,
        answer_mode=state.answer_mode,
    ):
        yield _start_event("expand_search_queries")
        expanded, ev = run_tool(
            "expand_search_queries",
            lambda: tool_expand_search_queries(
                question, intent=state.intent, institution=state.institution
            ),
        )
        yield ev
        state.tools_run.append("expand_search_queries")
        state.alt_queries = (expanded or {}).get("queries") or []

        yield _start_event("broaden_corpus_search")
        broadened, ev = run_tool(
            "broaden_corpus_search",
            lambda: tool_broaden_corpus_search(
                db,
                question,
                hits,
                intent=state.intent,
                top_k=max(top_k, 10),
                topic_terms=state.topic_terms,
            ),
        )
        yield ev
        state.tools_run.append("broaden_corpus_search")
        hits = (broadened or {}).get("hits") or hits

        if state.alt_queries:
            yield _start_event("research_corpus")
            researched, ev = run_tool(
                "research_corpus",
                lambda: tool_research_corpus(
                    db, state.alt_queries, hits, top_k=max(4, top_k - 1)
                ),
            )
            yield ev
            state.tools_run.append("research_corpus")
            hits = (researched or {}).get("hits") or hits

        denoised2, _ = run_tool(
            "filter_noise_docs",
            lambda: tool_filter_noise_docs(hits, intent=state.intent),
        )
        hits = (denoised2 or {}).get("hits") or hits
        filtered2, _ = run_tool(
            "filter_by_year",
            lambda: tool_filter_by_year(
                hits, wants_current=state.wants_current, intent=state.intent
            ),
        )
        hits = (filtered2 or {}).get("hits") or hits
        state.hits = hits

        yield _start_event("verify_evidence")
        verified2, ev = run_tool(
            "verify_evidence",
            lambda: tool_verify(
                hits,
                question,
                answer_mode=state.answer_mode,
                wants_list=state.wants_list,
            ),
        )
        yield ev
        state.tools_run.append("verify_evidence")
        new_gate = (verified2 or {}).get("gate") or "missing"
        new_usable = (verified2 or {}).get("usable") or []
        # Union usable sets when both supported — maximize coverage (esp. listings)
        if best_gate == "supported" and new_gate == "supported":
            merged_u = _merge_hits(best_usable, new_usable, limit=12)
            state.gate, state.usable = "supported", merged_u
            best_gate, best_usable = "supported", list(merged_u)
        elif state.wants_list or state.answer_mode == "list":
            # Prefer the side with more distinct documents
            def _docs(xs: list) -> int:
                return len({getattr(h, "document_id", id(h)) for h in xs})

            if new_gate == "supported" and (
                best_gate != "supported" or _docs(new_usable) >= _docs(best_usable)
            ):
                merged_u = _merge_hits(new_usable, best_usable, limit=12)
                state.gate, state.usable = "supported", merged_u
                best_gate, best_usable = "supported", list(merged_u)
            else:
                state.gate, state.usable = best_gate, best_usable
        else:
            rank = {"missing": 0, "conflict": 1, "supported": 2}
            if rank.get(new_gate, 0) > rank.get(best_gate, 0) or (
                new_gate == best_gate and len(new_usable) > len(best_usable)
            ):
                state.gate, state.usable = new_gate, new_usable
                best_gate, best_usable = new_gate, list(new_usable)
            else:
                state.gate, state.usable = best_gate, best_usable
                hits = best_usable or hits

    # 11–12 contact tools (optional unless contact intent)
    if state.intent == "contact" or state.institution:
        yield _start_event("extract_contact_fields")
        extracted, ev = run_tool(
            "extract_contact_fields",
            lambda: tool_extract_contact_fields(
                state.usable, institution=state.institution
            ),
        )
        yield ev
        state.tools_run.append("extract_contact_fields")
        state.extracted_contacts = extracted or {}

        yield _start_event("lookup_known_contacts")
        known, ev = run_tool(
            "lookup_known_contacts",
            lambda: tool_lookup_known_contacts(state.institution),
        )
        yield ev
        state.tools_run.append("lookup_known_contacts")
        state.known_contact = (known or {}).get("contact")

    if state.intent == "contact" and state.known_contact:
        state.gate = "supported"
        state.contact_answer = _format_contact_answer(
            state.known_contact, state.language
        )
        state.confidence = "high"
        state.confidence_score = 0.92

    # 13 classify
    yield _start_event("classify_sources")
    classified, ev = run_tool(
        "classify_sources", lambda: tool_classify_sources(state.usable)
    )
    yield ev
    state.tools_run.append("classify_sources")
    state.source_meta = (classified or {}).get("sources") or []

    # 14 conflicts (optional — deadlines only)
    if question_about_deadline(question):
        yield _start_event("detect_conflicts")
        conflicted, ev = run_tool(
            "detect_conflicts",
            lambda: tool_detect_conflicts(state.usable, question),
        )
        yield ev
        state.tools_run.append("detect_conflicts")
        state.conflicts = (conflicted or {}).get("conflicts") or []
        if state.conflicts:
            state.gate = "conflict"

    # 15 contact resolve
    yield _start_event("resolve_contact")
    contact, ev = run_tool(
        "resolve_contact",
        lambda: tool_resolve_contact(
            db,
            question,
            institution=state.institution,
            known=state.known_contact,
        ),
    )
    yield ev
    state.tools_run.append("resolve_contact")
    state.contact = contact

    # 16 confidence
    yield _start_event("estimate_confidence")
    conf, ev = run_tool(
        "estimate_confidence",
        lambda: tool_estimate_confidence(
            state.gate,
            state.usable,
            question,
            state.conflicts,
            known_contact=state.known_contact,
            intent=state.intent,
        ),
    )
    yield ev
    state.tools_run.append("estimate_confidence")
    if conf:
        state.confidence = conf.get("level") or "low"
        state.confidence_score = float(conf.get("score") or 0)

    # 17–22 multi-document reading + expand chunks
    doc_ids: list[int] = []
    for h in state.usable or []:
        did = getattr(h, "document_id", None)
        if did and did not in doc_ids:
            doc_ids.append(int(did))
    if state.urls_in_question:
        yield _start_event("find_document_by_url")
        found, ev = run_tool(
            "find_document_by_url",
            lambda: tool_find_document_by_url(db, state.urls_in_question[0]),
        )
        yield ev
        state.tools_run.append("find_document_by_url")
        if found and found.get("found") and found.get("id"):
            if int(found["id"]) not in doc_ids:
                doc_ids.insert(0, int(found["id"]))

    if doc_ids:
        yield _start_event("read_multi_documents")
        multi, ev = run_tool(
            "read_multi_documents",
            lambda: tool_read_multi_documents(db, doc_ids[:6]),
        )
        yield ev
        state.tools_run.append("read_multi_documents")
        # Enrich usable with fuller previews as synthetic chunks when helpful
        if multi and multi.get("documents"):
            for d in multi["documents"]:
                preview = d.get("preview") or ""
                if len(preview) < 80:
                    continue
                # attach fuller text onto matching usable hit
                for h in state.usable:
                    if h.document_id == d["id"] and len(preview) > len(h.content or ""):
                        h.content = preview
                        break

        yield _start_event("expand_related_chunks")
        expanded_ch, ev = run_tool(
            "expand_related_chunks",
            lambda: tool_expand_related_chunks(db, state.usable, per_doc=3, max_extra=10),
        )
        yield ev
        state.tools_run.append("expand_related_chunks")
        extra = (expanded_ch or {}).get("hits") or []
        if extra:
            state.usable = _merge_hits(state.usable, extra, limit=12)
            state.hits = _merge_hits(state.hits or [], extra, limit=16)
            # Re-verify after expanding so fuller multi-doc text can upgrade coverage
            if state.wants_list or state.answer_mode == "list" or state.wants_current:
                re_v, _ = run_tool(
                    "verify_evidence",
                    lambda: tool_verify(
                        state.hits or state.usable,
                        question,
                        answer_mode=state.answer_mode,
                        wants_list=state.wants_list,
                    ),
                )
                if re_v and re_v.get("gate") == "supported" and re_v.get("usable"):
                    state.gate = "supported"
                    state.usable = _merge_hits(
                        re_v["usable"], state.usable, limit=12
                    )

        # still read chunks for top 3 docs (timeline UI)
        for did in doc_ids[:3]:
            yield _start_event("read_document_chunks")
            _chunks, ev = run_tool(
                "read_document_chunks",
                lambda d=did: tool_read_document_chunks(db, document_id=int(d), limit=6),
            )
            yield ev
            state.tools_run.append("read_document_chunks")

        if doc_ids:
            yield _start_event("get_document_changes")
            _ch, ev = run_tool(
                "get_document_changes",
                lambda: tool_get_document_changes(db, document_id=int(doc_ids[0])),
            )
            yield ev
            state.tools_run.append("get_document_changes")

    if state.intent in ("deadline", "general") or question_about_deadline(question):
        yield _start_event("extract_dates_deadlines")
        _dates, ev = run_tool(
            "extract_dates_deadlines",
            lambda: tool_extract_dates_deadlines(state.usable or state.hits),
        )
        yield ev
        state.tools_run.append("extract_dates_deadlines")

    yield _start_event("lookup_topic_link")
    _topic, ev = run_tool(
        "lookup_topic_link", lambda: tool_lookup_topic_link(db, question)
    )
    yield ev
    state.tools_run.append("lookup_topic_link")

    # exact phrase from quoted text in question
    quoted = re.findall(r"[„\"«](.{4,80})[”\"»]", question)
    if quoted:
        yield _start_event("search_exact_phrase")
        _ex, ev = run_tool(
            "search_exact_phrase",
            lambda: tool_search_exact_phrase(db, quoted[0]),
        )
        yield ev
        state.tools_run.append("search_exact_phrase")

    # refresh when user asks to update / reîncarcă
    if re.search(
        r"\b(actualizeaz|reîmprospăt|reimprospat|refresh|update\s+doc)\b",
        question,
        re.I,
    ):
        target = state.urls_in_question[0] if state.urls_in_question else None
        if not target and state.usable:
            target = getattr(state.usable[0], "document_url", None)
        if target:
            yield _start_event("refresh_document")
            _ref, ev = run_tool(
                "refresh_document", lambda: tool_refresh_document(db, url=target)
            )
            yield ev
            state.tools_run.append("refresh_document")

    if re.search(
        r"\b(corpus|surse|index|câte\s+document|cate\s+document|coverage)\b",
        question,
        re.I,
    ):
        yield _start_event("list_recent_documents")
        _recent, ev = run_tool(
            "list_recent_documents", lambda: tool_list_recent_documents(db)
        )
        yield ev
        state.tools_run.append("list_recent_documents")

        yield _start_event("source_coverage")
        _cov, ev = run_tool("source_coverage", lambda: tool_source_coverage(db))
        yield ev
        state.tools_run.append("source_coverage")

    # corpus health (light)
    yield _start_event("corpus_health")
    health, ev = run_tool("corpus_health", lambda: tool_corpus_health(db))
    yield ev
    state.tools_run.append("corpus_health")
    state.health = health or {}

    yield state
