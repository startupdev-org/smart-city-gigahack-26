from __future__ import annotations

"""Municipal relevance keywords for discovering links beyond sitemaps."""

# Stems / phrases — kept lowercase; match against url + anchor text
_BASE = [
    # RO administrative
    "autorizat", "autoriza", "certificat", "urbanism", "construire", "construc",
    "regulament", "hotarare", "hotărâre", "dispozitie", "dispoziție", "decizie",
    "ordin", "anunt", "anunț", "concurs", "licitat", "achizit", "achiziț",
    "transparent", "acte", "document", "formular", "cerere", "dosar", "aviz",
    "termen", "taxa", "taxă", "tarife", "plata", "plată", "servici", "ghid",
    "cetatean", "cetățean", "primarie", "primărie", "consiliu", "municipal",
    "sector", "pretura", "pretură", "directie", "direcție", "departament",
    "function", "funcți", "posturi", "angajari", "angajări", "vacant",
    "parcare", "transport", "mobilitate", "rute", "autobuz", "troleibuz",
    "spatii verd", "spații verd", "defriș", "defris", "salubritate", "gunoi",
    "apa", "apă", "canalizare", "incalzire", "încălzire", "gaze",
    "educat", "scoala", "școală", "gradinit", "grădiniț", "elevi", "studii",
    "sanatate", "sănătate", "spital", "policlini", "medic", "vaccin",
    "social", "ajutor", "indemnizat", "pensie", "handicap", "familie",
    "tineret", "cultura", "cultură", "sport", "eveniment", "festival",
    "investit", "business", "impozit", "cadastru", "proprietate", "teren",
    "locuint", "locuinț", "bloc", "reabilitare", "infrastructur",
    "proiect", "program", "strategie", "plan", "buget", "raport",
    "sedinta", "ședință", "agenda", "proces-verbal", "pv-", "anexa", "anexă",
    "contact", "adresa", "adresă", "telefon", "program de lucru", "programul",
    "online", "electronic", "portal", "servicii publice", "e-servicii",
    "noutat", "stiri", "știri", "comunicat", "presa", "presă", "media",
    "download", "descarc", "pdf", "docx", "xlsx", "fisier", "fișier",
    "pagina", "pagină", "arhiva", "arhivă", "biblioteca", "bibliotecă",
    # RU
    "разрешени", "строительств", "сертификат", "градостроител", "регламент",
    "постановлен", "распоряжен", "решени", "объявлен", "конкурс", "закупк",
    "прозрачн", "документ", "заявлен", "срок", "налог", "тариф", "услуг",
    "мэри", "муницип", "претур", "управлен", "ваканси", "парковк",
    "транспорт", "маршрут", "зелен", "отход", "образован", "школ", "детсад",
    "здрав", "больниц", "социал", "молодеж", "мероприят", "инвестиц",
    "бюджет", "отчет", "заседан", "новост", "пресс", "контакт", "адрес",
    # EN / cross
    "regulation", "decision", "tender", "procurement", "vacancy", "news",
    "event", "service", "document", "form", "application", "permit",
    "building", "urban", "transport", "health", "education", "budget",
    "meeting", "minutes", "annex", "download", "contact", "about",
    # pagination / browse
    "page=", "pagina=", "paged=", "/page/", "urmator", "următor", "next",
    "previous", "inapoi", "înapoi", "mai mult", "vezi toate", "load more",
    "show more", "toate anun", "toate nout", "archive", "categoria",
    "category", "tag/", "wp-content/uploads", "attached_files", "upload",
    "files/", "media/", "publicatii", "publicații", "legislatie", "legislație",
]

# Extra domain-specific expansions
_EXTRA = [
    "dgaurf", "dglca", "rtec", "autourban", "exdrupo", "agsv", "acc.md",
    "help.chisinau", "invest.chisinau", "visit.chisinau", "comert",
    "botanica", "ciocana", "rascani", "râșcani", "buiucani", "centru",
    "suburbii", "proiecte.chisinau", "e-tineret", "infocom", "liftservice",
    "autosalubritate", "escoala", "egradinita", "extrascolar", "educatieonline",
    "mobilitatechisinau", "amt-", "dets", "dgams", "chisinauedu",
    "certificat de urbanism", "autorizatie de construire", "autorizație",
    "extras din registru", "cadastru", "bunuri imobile", "aviz ism",
    "inspectia de stat", "inspecția de stat", "pompieri", "sanepid",
    "plan urbanistic", "pug", "pud", "puz", "zona verde", "tocire",
    "amenzi", "contraventie", "contravenție", "politia locala", "poliția locală",
    "ghiseu", "ghișeu", "one stop", "front desk", "reception", "recepție",
    "orar", "program lucru", "luni", "vineri", "programare online",
    "petitie", "petiție", "sesizare", "reclamatie", "reclamație",
    "informatie de interes public", "acces la informatie", "legea 982",
    "consiliul municipal", "cmc", "primarul general", "viceprimar",
    "directia generala", "direcția generală", "sectia", "secția",
]


def _expand(stems: list[str]) -> list[str]:
    out: list[str] = []
    for s in stems:
        s = s.strip().lower()
        if not s:
            continue
        out.append(s)
        # light morphological variants
        if s.endswith(("a", "ă", "e", "i")) and len(s) > 4:
            out.append(s[:-1])
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


KEYWORDS: list[str] = _expand(_BASE + _EXTRA)

# Pad toward ~1000 with systematic municipal suffixes
_SUFFIXES = [
    "ro", "ru", "md", "pdf", "html", "doc", "2020", "2021", "2022", "2023",
    "2024", "2025", "2026", "nr", "art", "cap", "anexa1", "anexa2", "anexa3",
]
_TOPICS = [
    "urbanism", "constructii", "construcții", "transport", "educatie", "educație",
    "sanatate", "sănătate", "social", "mediu", "finante", "finanțe", "juridic",
    "cadastru", "locativ", "comunal", "cultura", "cultură", "sport", "tineret",
    "investitii", "investiții", "turism", "comert", "comerț", "securitate",
]
for topic in _TOPICS:
    for suf in _SUFFIXES:
        KEYWORDS.append(f"{topic}-{suf}")
        KEYWORDS.append(f"{topic}_{suf}")
        KEYWORDS.append(f"{topic}/{suf}")

# dedupe final
_seen: set[str] = set()
_final: list[str] = []
for k in KEYWORDS:
    if k not in _seen and len(k) >= 2:
        _seen.add(k)
        _final.append(k)
KEYWORDS = _final


def keyword_hits(text: str) -> list[str]:
    blob = (text or "").lower()
    return [k for k in KEYWORDS if k in blob][:20]


def is_keyword_relevant(url: str, anchor: str = "") -> bool:
    blob = f"{url} {anchor}".lower()
    return any(k in blob for k in KEYWORDS)
