"""Discover URLs buried in CSS / JS assets (not only HTML <a href>)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from backend.crawler.allowlist import normalize_url
from backend.crawler.fetcher import Fetcher

logger = logging.getLogger(__name__)

# Absolute or root-relative http(s) URLs, and common quoted path forms
_ABS_URL_RE = re.compile(
    r"""(?<![\w./-])(https?://[^\s"'<>\\)]+)""",
    re.I,
)
_CSS_URL_RE = re.compile(
    r"""url\(\s*['"]?([^)'"\s]+)['"]?\s*\)""",
    re.I,
)
_QUOTED_PATH_RE = re.compile(
    r"""['"](/[a-zA-Z0-9][^'"]{2,240})['"]""",
)
_JS_ROUTE_RE = re.compile(
    r"""(?:href|src|url|path|link|permalink|endpoint)\s*[:=]\s*['"]([^'"]+)['"]""",
    re.I,
)

_SKIP_EXT = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
    ".css",
    ".js",
)


def _looks_useful(url: str) -> bool:
    u = (url or "").lower().split("?", 1)[0]
    if not u or u.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#")):
        return False
    if any(u.endswith(ext) for ext in _SKIP_EXT):
        return False
    return True


def extract_urls_from_text(base_url: str, text: str) -> list[str]:
    """Pull candidate page/document URLs from CSS or JS source text."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        raw = (raw or "").strip().rstrip("\\").rstrip(".,);]")
        if not raw or not _looks_useful(raw):
            return
        try:
            abs_u = normalize_url(urljoin(base_url, raw))
        except Exception:  # noqa: BLE001
            return
        if not abs_u or abs_u in seen:
            return
        # skip pure asset hosts noise
        path = urlparse(abs_u).path or ""
        if path.endswith(_SKIP_EXT):
            return
        seen.add(abs_u)
        found.append(abs_u)

    for m in _ABS_URL_RE.finditer(text or ""):
        add(m.group(1))
    for m in _CSS_URL_RE.finditer(text or ""):
        add(m.group(1))
    for m in _QUOTED_PATH_RE.finditer(text or ""):
        add(m.group(1))
    for m in _JS_ROUTE_RE.finditer(text or ""):
        add(m.group(1))

    return found


def collect_asset_urls_from_html(page_url: str, soup) -> list[str]:
    """script[src] + link[rel=stylesheet] (+ modulepreload)."""
    assets: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("script", src=True):
        abs_u = normalize_url(urljoin(page_url, tag["src"]))
        if not abs_u or abs_u in seen:
            continue
        low = abs_u.lower()
        if low.endswith((".js", ".mjs")) or ".js?" in low or "/js/" in low:
            seen.add(abs_u)
            assets.append(abs_u)
    for tag in soup.find_all("link", href=True):
        rel = " ".join(tag.get("rel") or []).lower()
        href = tag["href"]
        abs_u = normalize_url(urljoin(page_url, href))
        if not abs_u or abs_u in seen:
            continue
        low = abs_u.lower()
        if "stylesheet" in rel or low.endswith(".css") or ".css?" in low:
            seen.add(abs_u)
            assets.append(abs_u)
    return assets[:40]


def discover_links_from_assets(
    page_url: str,
    asset_urls: list[str],
    *,
    fetcher: Fetcher | None = None,
    max_assets: int = 12,
    max_links: int = 200,
) -> list[tuple[str, str]]:
    """
    Fetch CSS/JS referenced by the page and extract embedded URLs.
    Returns list of (url, anchor_hint).
    """
    fetcher = fetcher or Fetcher()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for asset in asset_urls[:max_assets]:
        try:
            res = fetcher.fetch(asset)
            if not res or res.status >= 400 or not res.body:
                continue
            text = res.body.decode("utf-8", errors="ignore")
            if len(text) > 2_000_000:
                text = text[:2_000_000]
            kind = "css" if ".css" in asset.lower() else "js"
            for u in extract_urls_from_text(res.final_url or page_url, text):
                if u in seen or u == page_url:
                    continue
                seen.add(u)
                out.append((u, f"from-{kind}"))
                if len(out) >= max_links:
                    return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("asset link scan failed %s: %s", asset, exc)
    return out
