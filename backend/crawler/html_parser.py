from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from backend.crawler.allowlist import looks_like_document, normalize_url

_PAGINATION_RE = re.compile(
    r"(?:"
    r"next|previous|prev|următor|urmator|înapoi|inapoi|înainte|inainte|"
    r"mai\s+mult|vezi\s+toate|toate\s+(?:anun|nout|știr|stir)|"
    r"load\s*more|show\s*more|older|newer|page\s*\d+|pagina\s*\d+|"
    r"следующ|предыдущ|далее|назад|ещё|еще"
    r")",
    re.IGNORECASE,
)

_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "nav",
    "footer",
    "form",
)

_CONTENT_SELECTORS = [
    ".main-article",
    ".single-article .main-article",
    "#single-article .main-article",
    "article .entry-content",
    ".entry-content",
    "article .post-content",
    ".post-content",
    ".td-post-content",
    ".single-post-content",
    "[itemprop='articleBody']",
    "article .elementor-widget-theme-post-content",
    ".elementor-widget-theme-post-content .elementor-widget-container",
    ".single-article",
    ".article-section",
    "main article",
    "article",
]

_STRIP_CLASS_EXACT = {
    "sidebar",
    "side-bar",
    "widget-area",
    "secondary",
    "site-header",
    "site-footer",
    "main-navigation",
    "primary-menu",
    "breadcrumb",
    "breadcrumbs",
    "related-posts",
    "related_posts",
    "jp-relatedposts",
    "yarpp",
    "recent-posts",
    "recent_posts",
    "popular-posts",
    "share-buttons",
    "share_buttons",
    "social-share",
    "social-links",
    "social-icons",
    "comments",
    "comment-form",
    "comment-area",
    "newsletter",
    "promo-banner",
    "adsbygoogle",
    "elementor-location-header",
    "elementor-location-footer",
    "accessibility",
    "a11y",
    "post-navigation",
    "nav-links",
    "footer",
}

_STRIP_CLASS_PREFIXES = (
    "menu-item",
    "related-post",
    "share-button",
    "cookie-",
    "cookies-",
)

_STRIP_CLASS_SUBSTRINGS = (
    "articole-recente",
    "articole_recente",
    "alte-stiri",
    "alte-știri",
    "alte_stiri",
)


def is_pagination_hint(url: str, anchor: str = "") -> bool:
    blob = f"{url} {anchor}".lower()
    if _PAGINATION_RE.search(anchor or ""):
        return True
    if re.search(r"([?&](page|paged|p)=\d+)|(/page/\d+)|(/pagina/\d+)", blob):
        return True
    return False


def _should_strip(tag: Tag) -> bool:
    if tag.name in ("aside", "nav", "footer"):
        return True
    if tag.name == "header":
        return bool(tag.find("nav"))
    if tag.name == "body":
        return False
    role = str(tag.get("role") or "")
    if role in ("navigation", "banner", "contentinfo", "complementary"):
        return True
    tid = str(tag.get("id") or "").lower()
    if tid in {"sidebar", "secondary", "footer", "comments", "related", "cookie"} or tid.startswith(
        ("sidebar", "menu-", "footer")
    ):
        return True
    for cls in tag.get("class") or []:
        c = str(cls).lower()
        # CRITICAL: "no-sidebar" must NOT match as sidebar
        if c in {"no-sidebar", "has-no-sidebar"}:
            continue
        if c in _STRIP_CLASS_EXACT:
            return True
        if any(c.startswith(p) for p in _STRIP_CLASS_PREFIXES):
            return True
        if any(s in c for s in _STRIP_CLASS_SUBSTRINGS):
            return True
    return False


def _clean_chrome(soup: BeautifulSoup) -> None:
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    to_strip: list[Tag] = []
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _should_strip(tag):
            to_strip.append(tag)
    for tag in to_strip:
        try:
            tag.decompose()
        except Exception:  # noqa: BLE001
            pass


def _pick_main_node(soup: BeautifulSoup) -> Tag:
    scored: list[tuple[int, Tag]] = []
    for sel in _CONTENT_SELECTORS:
        for node in soup.select(sel):
            n = len(node.get_text(strip=True))
            if n < 120:
                continue
            bonus = 0
            classes = " ".join(node.get("class") or []).lower()
            if "main-article" in classes or "entry-content" in classes or "post-content" in classes:
                bonus = 5000
            elif "single-article" in classes or "article-section" in classes:
                bonus = 2000
            elif node.name == "article":
                bonus = -500
            scored.append((n + bonus, node))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    if soup.body:
        return soup.body
    return soup


def _cut_after_markers(text: str) -> str:
    markers = [
        r"\nAlte știri care te interesează\n",
        r"\nAlte stiri care te intereseaza\n",
        r"\nArticole Recente\n",
        r"\nArticole recente\n",
        r"\nPOSTĂRI ASEMĂNATOARE\n",
        r"\nPostări asemănătoare\n",
        r"\nRelated posts\n",
        r"\nComentarii\n",
        r"\nComments\n",
        r"\nVezi toate\n",
        r"\nDistribuie:\n",
        r"\nShare:\n",
        r"\nArticolul următor\n",
        r"\nArticolul anterior\n",
        r"\nTags:\n",
    ]
    cut = len(text)
    for m in markers:
        match = re.search(m, text, flags=re.IGNORECASE)
        if not match:
            continue
        # Related-posts / comments can be cut even early; other markers need some body first
        soft = any(
            k in m.lower()
            for k in ("postări", "postari", "related", "comentarii", "comments", "tags:")
        )
        if soft or match.start() > 80:
            cut = min(cut, match.start())
    return text[:cut].strip()


_NAV_BLOB_RE = re.compile(
    r"(?:"
    r"DISPOZI[TȚ]IILE\s+PRETORULUI|"
    r"Căutați\s+pe\s+Internet|"
    r"INTEGRITATE\s+[ȘŞ]I\s+ANTICORUP[TȚ]IE|"
    r"ORGANELE\s+DE\s+DREPT|"
    r"Func[tț]ii\s+vacante|"
    r"Declara[tț]ia\s+de\s+r[aă]spundere\s+managerial[aă]|"
    r"Transparen[tț]a\s+[iî]n\s+procesul\s+decizional|"
    r"Lista\s+schemelor\s+de\s+amplasare|"
    r"Informa[tț]ia\s+privind\s+cheltuielile\s+efectuate"
    r")",
    re.IGNORECASE,
)


def scrub_indexed_text(text: str) -> str:
    """Remove residual chrome / sidebar widget lines from indexed or evidence text."""
    text = text or ""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if len(s) <= 42 and re.fullmatch(
            r"(Pretura|Pretor|Vicepretori|Organigrama|Galerie|PDCP|Achizi[tț]ii|"
            r"Transparen[tț]a|Activitatea|INSTITU[TŢ]II|Sectorul\s+\w+|Comisii\s+permanente|"
            r"Aparatul\s+Preturii|Secretarul-Preturii|Audien[tț]a\s+cet[aă][tț]enilor|"
            r"Regulamente\s+[șs]i\s+atribu[tț]ii|Servicii\s+prestate|Toate|Activit[aă][tț]i)",
            s,
            re.I,
        ):
            continue
        if _NAV_BLOB_RE.search(s) and len(s) < 120:
            continue
        if re.fullmatch(r"\d{1,5}", s):
            continue
        lines.append(s)
    text = "\n".join(lines)
    text = _cut_after_markers(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # WordPress Download Manager / theme placeholders — never index these
    text = re.sub(r"\[expire_date\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[featured_image\]", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"Download is available until\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    drop_line = re.compile(
        r"^(?:"
        r"version|mărime fișier|marime fisier|file size|număr de descărcări|"
        r"numar de descarcari|download count|încărcare fișier|incarcare fisier|"
        r"upload(?:ed)?|ultimul update|last update|descarcă|download|"
        r"\d+\s*fi[sș]ier\(e\)|\d+\s*file\(s\)"
        r")\s*:?\s*$",
        re.IGNORECASE,
    )
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.fullmatch(r"(citește|citeste)\s+mai\s+mult", s, re.I):
            continue
        if re.fullmatch(r"distribuie:?|share:?", s, re.I):
            continue
        if drop_line.match(s):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:KB|MB|GB)", s, re.I):
            continue
        lines.append(s)
    text = "\n".join(lines).strip()
    return _cut_after_markers(text)


def extract_html(url: str, body: bytes) -> tuple[str, str, list[tuple[str, str]]]:
    """
    Returns (title, main-article text, links).
    Sidebars / related posts / chrome are excluded from indexed text,
    but ALL page links are collected before chrome stripping (maximal crawl).
    Also discovers URLs embedded in linked CSS/JS assets.
    """
    soup = BeautifulSoup(body, "lxml")

    # Collect links BEFORE chrome strip so nav / footer / archives are followed
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        abs_url = normalize_url(urljoin(url, href))
        anchor = a.get_text(" ", strip=True)[:120]
        if not anchor:
            anchor = (a.get("aria-label") or a.get("title") or "")[:120]
        links.append((abs_url, anchor))

    for tag in soup.find_all(["button", "div", "span"], attrs={"data-href": True}):
        abs_url = normalize_url(urljoin(url, tag["data-href"]))
        anchor = tag.get_text(" ", strip=True)[:120]
        links.append((abs_url, anchor))

    for tag in soup.find_all(["iframe", "embed", "object"]):
        for attr in ("src", "data"):
            if tag.get(attr):
                abs_url = normalize_url(urljoin(url, tag[attr]))
                links.append((abs_url, ""))

    for link in soup.find_all("link", rel=True, href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "next" in rel or "prev" in rel:
            links.append((normalize_url(urljoin(url, link["href"])), rel))

    # CSS / JS asset discovery (URLs not present as <a href>)
    try:
        from backend.crawler.asset_links import (
            collect_asset_urls_from_html,
            discover_links_from_assets,
        )

        assets = collect_asset_urls_from_html(url, soup)
        if assets:
            extra = discover_links_from_assets(url, assets)
            links.extend(extra)
    except Exception:  # noqa: BLE001
        pass

    _clean_chrome(soup)

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    main = _pick_main_node(soup)
    nested_strip: list[Tag] = []
    for child in main.find_all(True):
        if isinstance(child, Tag) and _should_strip(child):
            nested_strip.append(child)
    for child in nested_strip:
        try:
            child.decompose()
        except Exception:  # noqa: BLE001
            pass

    text = _normalize_text(main.get_text("\n", strip=True))
    text = scrub_indexed_text(text)

    if h1 and len(text) < 200:
        parent = h1.parent
        for _ in range(8):
            if parent is None:
                break
            candidate = _normalize_text(parent.get_text("\n", strip=True))
            if len(candidate) > len(text):
                text = candidate
            if len(text) >= 300:
                break
            parent = getattr(parent, "parent", None)

    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for link, anchor in links:
        if link not in seen:
            seen.add(link)
            uniq.append((link, anchor))

    uniq.sort(
        key=lambda x: (
            0 if looks_like_document(x[0]) else 1,
            0 if is_pagination_hint(x[0], x[1]) else 1,
            x[0],
        )
    )
    return title or urlparse(url).path or url, text, uniq
