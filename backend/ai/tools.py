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
from backend.db.models import Chunk, Document, TopicLink

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
    from backend.ai.language import resolve_answer_language

    lang_meta = resolve_answer_language(question, ui_language)
    urls = _URL_RE.findall(question or "")
    wants = bool(
        re.search(
            r"\b(acum|current|now|deschis|открыт|vacant|конкурс|astăzi|astazi|2026)\b",
            question or "",
            re.I,
        )
    )
    intent = "deadline" if question_about_deadline(question) else "general"
    if question_about_contact(question):
        intent = "contact"
    elif re.search(r"autoriz|construir|urbanism|разрешен|permit|building", question or "", re.I):
        intent = "autorizatie"
    elif re.search(r"concurs|vacant|angajar|ваканс|job\s*opening", question or "", re.I):
        intent = "concurs"
    return {
        "summary": (
            f"Q={lang_meta['question_language']}; "
            f"answer={lang_meta['answer_language']}; "
            f"ui={lang_meta.get('ui_language') or '—'}; "
            f"intent={intent}"
        ),
        "language": lang_meta["answer_language"],
        "language_meta": lang_meta,
        "intent": intent,
        "wants_current": wants,
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
    if intent != "contact":
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


def tool_search_corpus(db: Session, question: str, top_k: int = 5) -> dict[str, Any]:
    hits = HybridRetriever(db).search(question, top_k=top_k)
    return {
        "summary": f"{len(hits)} pasaje găsite",
        "hits": hits,
        "titles": [h.document_title for h in hits[:5]],
    }


def tool_filter_noise_docs(
    hits: list[RetrievedChunk], *, intent: str
) -> dict[str, Any]:
    if intent != "contact" or not hits:
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
    hits: list[RetrievedChunk], *, wants_current: bool
) -> dict[str, Any]:
    year = _now_year()
    if not wants_current or not hits:
        return {"summary": "Fără filtru temporal", "hits": hits, "kept": len(hits)}
    fresh = [h for h in hits if (_chunk_year(h) or year) >= year - 0]
    if fresh:
        return {
            "summary": f"Păstrate {len(fresh)} surse din {year}+",
            "hits": fresh,
            "kept": len(fresh),
            "dropped": len(hits) - len(fresh),
        }
    return {
        "summary": f"Nicio sursă {year}; păstrăm istorice ({len(hits)})",
        "hits": hits,
        "kept": len(hits),
        "historical_only": True,
    }


def tool_verify(hits: list[RetrievedChunk], question: str) -> dict[str, Any]:
    gate, usable = verify_evidence(hits, question=question)
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


_SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("autorizație", "autorizatie", "permis", "e-permis", "construire", "building permit"),
    ("contact", "telefon", "email", "adresă", "adresa", "phone"),
    ("pretura", "sector", "botanica", "buiucani", "ciocana", "râșcani", "rascani"),
    ("concurs", "funcție vacantă", "functii vacante", "vacancy", "angajare"),
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
    gate: str, usable: list[RetrievedChunk], intent: str
) -> bool:
    if intent == "contact" and usable:
        # contact may still use curated lookup; research if no contact-like hit
        blob = " ".join(
            f"{h.document_title or ''} {h.content or ''}" for h in usable[:3]
        ).lower()
        if any(k in blob for k in ("telefon", "email", "@", "contact", "str.")):
            return False
    if gate == "missing":
        return True
    if len(usable) < 2:
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
        lambda: tool_search_corpus(db, state.search_query, top_k=top_k),
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
        lambda: tool_filter_by_year(hits, wants_current=state.wants_current),
    )
    yield ev
    state.tools_run.append("filter_by_year")
    hits = (filtered or {}).get("hits") or hits
    state.hits = hits

    # 8 verify
    yield _start_event("verify_evidence")
    verified, ev = run_tool("verify_evidence", lambda: tool_verify(hits, question))
    yield ev
    state.tools_run.append("verify_evidence")
    state.gate = (verified or {}).get("gate") or "missing"
    state.usable = (verified or {}).get("usable") or []

    if state.fetched and state.gate == "missing":
        state.gate = "supported"

    # 9–10 optional research when evidence is weak
    if _needs_optional_research(state.gate, state.usable, state.intent):
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

        if state.alt_queries:
            yield _start_event("research_corpus")
            researched, ev = run_tool(
                "research_corpus",
                lambda: tool_research_corpus(
                    db, state.alt_queries, hits, top_k=max(3, top_k - 1)
                ),
            )
            yield ev
            state.tools_run.append("research_corpus")
            hits = (researched or {}).get("hits") or hits
            state.hits = hits

            # re-verify after research
            yield _start_event("verify_evidence")
            verified2, ev = run_tool(
                "verify_evidence", lambda: tool_verify(hits, question)
            )
            yield ev
            state.tools_run.append("verify_evidence")
            state.gate = (verified2 or {}).get("gate") or state.gate
            state.usable = (verified2 or {}).get("usable") or state.usable

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

    # 17 corpus health (optional — light)
    yield _start_event("corpus_health")
    health, ev = run_tool("corpus_health", lambda: tool_corpus_health(db))
    yield ev
    state.tools_run.append("corpus_health")
    state.health = health or {}

    yield state
