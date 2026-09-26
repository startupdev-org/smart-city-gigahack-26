from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
ANEXA_PATH = ROOT / "anexa.txt"

DOC_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".rtf",
    ".txt",
    ".csv",
}


@dataclass(frozen=True)
class SeedEntry:
    url: str
    category: str


def load_annex_seeds(path: Path | None = None) -> list[SeedEntry]:
    text = (path or ANEXA_PATH).read_text(encoding="utf-8")
    category = "general"
    seeds: list[SeedEntry] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Source PDF") or line.startswith("Annex"):
            continue
        if line.startswith("=") or line.startswith("All URLs"):
            continue
        if line and not line.startswith("http") and "====" not in line:
            # category headers like "Urban Mobility"
            if not line.startswith("Primăria") and len(line) < 80:
                category = line
            continue
        if line.startswith("http://") or line.startswith("https://"):
            url = line.rstrip("/")
            # keep trailing slash only for bare domains later — normalize without hash
            url = url.split("#")[0]
            if url not in seen:
                seen.add(url)
                seeds.append(SeedEntry(url=url, category=category))
    return seeds


def registrable_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def build_allowlist(seeds: list[SeedEntry] | None = None) -> set[str]:
    seeds = seeds or load_annex_seeds()
    hosts: set[str] = set()
    for s in seeds:
        h = registrable_host(s.url)
        if h:
            hosts.add(h)
            # also allow bare parent for *.chisinau.md style
            parts = h.split(".")
            if len(parts) >= 3 and parts[-2] == "chisinau" and parts[-1] == "md":
                hosts.add(".".join(parts[-2:]))  # chisinau.md
    # always allow main portal variants
    hosts.update({"chisinau.md", "new.chisinau.md"})
    return hosts


def is_allowed(url: str, allowlist: set[str]) -> bool:
    host = registrable_host(url)
    if not host:
        return False
    if host in allowlist:
        return True
    # subdomain of an allowed apex (e.g. www. / ro. / new.)
    for apex in allowlist:
        if host.endswith("." + apex) or host == apex:
            return True
    return False


def looks_like_document(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOC_EXTENSIONS)


def normalize_url(url: str) -> str:
    url = url.strip()
    url = url.split("#")[0]
    parsed = urlparse(url)
    # drop common tracking params later if needed
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    # collapse duplicate slashes in path
    path = re.sub(r"/{2,}", "/", path)
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def source_code_from_url(url: str) -> str:
    host = registrable_host(url).replace(".", "-")
    path = urlparse(url).path.strip("/").replace("/", "-")[:40]
    code = f"{host}-{path}" if path else host
    code = re.sub(r"[^a-zA-Z0-9_-]+", "-", code).strip("-").lower()
    return code[:64] or host[:64]


def should_enqueue_link(
    url: str,
    *,
    allowlist: set[str],
    depth: int = 0,
    anchor: str = "",
    from_sitemap: bool = False,
) -> bool:
    """Enqueue any URL on an allowlisted source domain (maximal crawl)."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if not is_allowed(url, allowlist):
        return False
    path = urlparse(url).path.lower()
    # skip obvious non-content endpoints
    skip_bits = (
        "/wp-login",
        "/wp-admin",
        "/logout",
        "/cart",
        "/checkout",
        "mailto:",
        "javascript:",
        ".css",
        ".js",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".mp4",
        ".mp3",
        ".zip",
        ".rar",
    )
    if any(b in path for b in skip_bits):
        return False
    # allow documents always; everything else on-domain is fair game
    _ = (depth, anchor, from_sitemap)  # kept for call-site compatibility
    return True
