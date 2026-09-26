from __future__ import annotations

import argparse
import logging
import time
from urllib.parse import urljoin, urlparse

from backend.config import get_settings
from backend.crawler.allowlist import (
    SeedEntry,
    build_allowlist,
    is_allowed,
    load_annex_seeds,
    looks_like_document,
    normalize_url,
    registrable_host,
    should_enqueue_link,
)
from backend.crawler.classifier import classify
from backend.crawler.fetcher import Fetcher
from backend.crawler.frontier import Frontier
from backend.crawler.html_parser import extract_html
from backend.crawler.ingest import ensure_source, ingest_text_document, mark_source_crawled
from backend.crawler.office import extract_doc_legacy, extract_docx, extract_xlsx
from backend.crawler.pdf import extract_pdf
from backend.crawler.soft404 import is_http_error, is_soft_404
from backend.db.database import SessionLocal, engine
from backend.db.models import Base, Document

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("crawler")


PRIORITY_KW = (
    "regulament",
    "autoriz",
    "hotar",
    "dispozit",
    "document",
    "noutat",
    "news",
    "post",
    "anunt",
    "transparent",
    "acte",
    "lege",
    "pdf",
    "decizie",
    "proiect",
    "servici",
)


def _priority_for_url(url: str, depth: int) -> int:
    # lower number = higher priority â€” documents ALWAYS first
    u = url.lower()
    if looks_like_document(url):
        return -20 + depth  # permanent top priority
    score = 40 + depth * 8
    if any(k in u for k in PRIORITY_KW):
        score -= 20
    if any(k in u for k in ("anunt", "anunÈ›", "noutat", "stiri", "È™tiri", "vacant", "concurs")):
        score -= 15
    if u.rstrip("/").count("/") <= 3:
        score -= 5
    return score


def _discover_sitemaps(seed_url: str, fetcher: Fetcher, *, max_urls: int = 8000) -> list[str]:
    """Aggressive sitemap discovery â€” robots + indexes, then ALL child sitemaps."""
    parsed = urlparse(seed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    found: list[str] = []
    seen: set[str] = set()
    child_sitemaps: list[str] = []
    tried: set[str] = set()

    def _queue_sm(u: str) -> None:
        n = normalize_url(u)
        if n not in tried and n not in child_sitemaps:
            child_sitemaps.append(n)

    def _absorb_xml(text: str) -> None:
        for part in text.split("<loc>"):
            if "</loc>" not in part:
                continue
            loc = part.split("</loc>", 1)[0].strip()
            if not loc.startswith("http"):
                continue
            loc_n = normalize_url(loc)
            low = loc_n.lower()
            if low.endswith(".xml") or "/sitemap" in low or "sitemap" in low.split("/")[-1]:
                _queue_sm(loc_n)
                continue
            if loc_n not in seen:
                seen.add(loc_n)
                found.append(loc_n)
                if len(found) >= max_urls:
                    return

    # 1) robots.txt â†’ Sitemap: lines (best entry point)
    robots = fetcher.fetch(urljoin(base, "/robots.txt"))
    if robots and robots.status < 400 and robots.body:
        for line in robots.body.decode("utf-8", errors="ignore").splitlines():
            if line.lower().startswith("sitemap:"):
                _queue_sm(line.split(":", 1)[1].strip())

    # 2) common indexes (only if robots gave nothing)
    boot = [
        urljoin(base, "/wp-sitemap.xml"),
        urljoin(base, "/sitemap.xml"),
        urljoin(base, "/sitemap_index.xml"),
        urljoin(base, "/sitemap-index.xml"),
    ]
    if not child_sitemaps:
        for sm in boot:
            _queue_sm(sm)
    else:
        # still try primary indexes in case robots was incomplete
        for sm in boot[:2]:
            _queue_sm(sm)

    # also try post/page sitemaps as extras
    for extra in (
        "/post-sitemap.xml",
        "/page-sitemap.xml",
        "/news-sitemap.xml",
        "/category-sitemap.xml",
    ):
        _queue_sm(urljoin(base, extra))

    i = 0
    while i < len(child_sitemaps) and len(found) < max_urls:
        child = child_sitemaps[i]
        i += 1
        if child in tried:
            continue
        tried.add(child)
        nested = fetcher.fetch(child)
        if not nested or nested.status >= 400 or not nested.body:
            continue
        before = len(found)
        _absorb_xml(nested.body.decode("utf-8", errors="ignore"))
        logger.info(
            "Sitemap %s â†’ +%d urls (host total %d, queue %d)",
            child[:90],
            len(found) - before,
            len(found),
            max(0, len(child_sitemaps) - i),
        )

    return found[:max_urls]


def run_crawl(
    *,
    max_pages: int | None = None,
    max_depth: int | None = None,
    only_hosts: list[str] | None = None,
    seed_limit: int | None = None,
) -> dict:
    settings = get_settings()
    max_pages = max_pages or settings.crawl_max_pages
    max_depth = max_depth if max_depth is not None else settings.crawl_max_depth
    delay = settings.crawl_delay_ms / 1000.0
    sitemap_cap = getattr(settings, "crawl_sitemap_max_urls", 8000)

    Base.metadata.create_all(bind=engine)
    seeds = load_annex_seeds()
    if seed_limit:
        seeds = seeds[:seed_limit]
    allowlist = build_allowlist(seeds)

    # Also pull active DB sources into seeds + allowlist (maximal coverage)
    with SessionLocal() as bootstrap:
        from backend.db.models import Source

        db_sources = (
            bootstrap.query(Source)
            .filter(Source.active.is_(True))
            .order_by(Source.id.asc())
            .all()
        )
        for src in db_sources:
            if not src.url:
                continue
            h = registrable_host(src.url)
            if h:
                allowlist.add(h)
            nurl = normalize_url(src.url)
            if not any(normalize_url(s.url) == nurl for s in seeds):
                seeds.append(
                    SeedEntry(url=nurl, category=src.category or "db-source")
                )

    if only_hosts:
        allowlist = {h.lower().removeprefix("www.") for h in only_hosts}

    frontier = Frontier()
    fetcher = Fetcher()

    # Seeds first â€” start fetching immediately; sitemaps load lazily per host
    seed_urls: list[str] = []
    for seed in seeds:
        host = registrable_host(seed.url)
        if only_hosts and host not in allowlist and not any(
            host.endswith("." + h) for h in allowlist
        ):
            continue
        url = normalize_url(seed.url)
        seed_urls.append(url)
        frontier.add(url, depth=0, priority=_priority_for_url(url, 0))

    sitemap_hosts_done: set[str] = set()
    host_seed: dict[str, str] = {}
    for url in seed_urls:
        h = registrable_host(url)
        host_seed.setdefault(h, url)

    logger.info(
        "MAXIMAL crawl ready: %d seed URLs, allowlist=%d domains, max_pages=%d depth=%d "
        "(sitemaps expand lazily per host)",
        len(frontier),
        len(allowlist),
        max_pages,
        max_depth,
    )

    stats = {
        "fetched": 0,
        "html": 0,
        "pdf": 0,
        "docx": 0,
        "xlsx": 0,
        "ingested": 0,
        "sources_added": 0,
        "errors": 0,
        "skipped": 0,
        "soft404": 0,
        "docs": 0,
        "sitemap_urls": 0,
    }

    def _expand_host_sitemap(host: str) -> None:
        if host in sitemap_hosts_done:
            return
        sitemap_hosts_done.add(host)
        seed = host_seed.get(host) or f"https://{host}/"
        added = 0
        try:
            for sm_url in _discover_sitemaps(seed, fetcher, max_urls=sitemap_cap):
                if not is_allowed(sm_url, allowlist):
                    continue
                if frontier.add(
                    sm_url,
                    depth=1,
                    priority=_priority_for_url(sm_url, 1),
                ):
                    added += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sitemap expand failed for %s: %s", host, exc)
        stats["sitemap_urls"] += added
        logger.info("Sitemap expand %s â†’ +%d URLs (frontier=%d)", host, added, len(frontier))

    with SessionLocal() as session:
        # ensure annex seeds exist as sources
        for seed in seeds:
            ensure_source(
                session,
                url=normalize_url(seed.url),
                name=registrable_host(seed.url),
                category=seed.category,
                priority="P0" if "chisinau.md" in seed.url or "transparenta" in seed.url else "P1",
                type_="documents" if looks_like_document(seed.url) else "portal",
            )
        session.commit()

        processed = 0
        while processed < max_pages:
            item = frontier.pop()
            if item is None:
                # try expanding remaining hosts that have seeds but no sitemap yet
                pending = [h for h in host_seed if h not in sitemap_hosts_done]
                if pending:
                    _expand_host_sitemap(pending[0])
                    continue
                break
            if item.depth > max_depth and not looks_like_document(item.url):
                stats["skipped"] += 1
                continue
            if not is_allowed(item.url, allowlist):
                stats["skipped"] += 1
                continue

            # lazy maximal sitemap harvest for this host
            _expand_host_sitemap(registrable_host(item.url))

            time.sleep(delay)
            result = fetcher.fetch(item.url)
            processed += 1
            if not result or not result.body or is_http_error(result.status):
                stats["errors"] += 1
                # purge known document if URL now 404s
                if result and is_http_error(result.status):
                    dead = session.query(Document).filter_by(url=normalize_url(item.url)).one_or_none()
                    if dead:
                        logger.info("Removing dead document (%s): %s", result.status, item.url)
                        session.delete(dead)
                        session.commit()
                continue

            stats["fetched"] += 1
            kind = classify(result)
            final_url = normalize_url(result.final_url)

            # Auto-add / reuse source at host level (not one source per PDF file)
            host = registrable_host(final_url)
            root = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}/"
            source = ensure_source(
                session,
                url=root,
                name=host,
                category="discovered-crawl",
                priority="P2",
                type_="portal",
            )
            session.commit()

            try:
                if kind == "html":
                    stats["html"] += 1
                    title, text, links = extract_html(final_url, result.body)
                    if is_soft_404(
                        status=result.status, title=title, text=text, url=final_url
                    ):
                        stats["soft404"] = stats.get("soft404", 0) + 1
                        stats["skipped"] += 1
                        logger.info("Soft-404 skip: %s (%s)", final_url, title[:60])
                        dead = session.query(Document).filter_by(url=final_url).one_or_none()
                        if dead:
                            session.delete(dead)
                            session.commit()
                        continue

                    ingest_text_document(
                        session,
                        source=source,
                        title=title,
                        url=final_url,
                        text=text,
                        mime_type="text/html",
                    )
                    stats["ingested"] += 1
                    mark_source_crawled(session, source)
                    session.commit()

                    # Absolute max: enqueue every allowlisted link from the page
                    for link, anchor in links:
                        # expand allowlist for municipal subdomains of known apexes
                        if not is_allowed(link, allowlist):
                            link_host = registrable_host(link)
                            expanded = False
                            for apex in list(allowlist):
                                if link_host.endswith("." + apex) or link_host == apex:
                                    allowlist.add(link_host)
                                    ensure_source(
                                        session,
                                        url=f"{urlparse(link).scheme}://{urlparse(link).netloc}/",
                                        name=link_host,
                                        category="auto-discovered-domain",
                                        priority="P2",
                                    )
                                    session.commit()
                                    stats["sources_added"] += 1
                                    expanded = True
                                    break
                            if not expanded:
                                continue
                        next_depth = item.depth + 1
                        if next_depth > max_depth and not looks_like_document(link):
                            continue
                        if not should_enqueue_link(
                            link,
                            allowlist=allowlist,
                            depth=next_depth,
                            anchor=anchor,
                            from_sitemap=False,
                        ):
                            continue
                        frontier.add(
                            link,
                            depth=next_depth,
                            priority=_priority_for_url(link, next_depth),
                        )

                elif kind == "pdf":
                    stats["pdf"] += 1
                    title, pages = extract_pdf(result.body)
                    full = "\n\n".join(
                        f"--- Pagina {i} ---\n{p}" for i, p in enumerate(pages, 1) if p
                    )
                    doc = ingest_text_document(
                        session,
                        source=source,
                        title=title or final_url.split("/")[-1],
                        url=final_url,
                        text=full,
                        mime_type="application/pdf",
                        pages=pages,
                    )
                    if doc:
                        stats["ingested"] += 1

                elif kind == "docx":
                    stats["docx"] += 1
                    text = extract_docx(result.body)
                    doc = ingest_text_document(
                        session,
                        source=source,
                        title=final_url.split("/")[-1],
                        url=final_url,
                        text=text,
                        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    if doc:
                        stats["ingested"] += 1

                elif kind == "xlsx":
                    stats["xlsx"] += 1
                    text = extract_xlsx(result.body)
                    doc = ingest_text_document(
                        session,
                        source=source,
                        title=final_url.split("/")[-1],
                        url=final_url,
                        text=text,
                        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    if doc:
                        stats["ingested"] += 1

                elif kind == "doc":
                    text = extract_doc_legacy(result.body)
                    if text:
                        ingest_text_document(
                            session,
                            source=source,
                            title=final_url.split("/")[-1],
                            url=final_url,
                            text=text,
                            mime_type="application/msword",
                        )
                        stats["ingested"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as exc:  # noqa: BLE001
                logger.exception("Process failed %s: %s", final_url, exc)
                stats["errors"] += 1
                session.rollback()

            logger.info(
                "progress %d/%d frontier=%d seen=%d kind=%s url=%s",
                processed,
                max_pages,
                len(frontier),
                frontier.seen_count,
                kind,
                final_url[:100],
            )

    stats["frontier_left"] = len(frontier)
    stats["seen"] = frontier.seen_count
    logger.info("Crawl done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="CivicAI maximal crawler (HTML/PDF/DOCX/XLSX)")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="Limit crawl to host(s), e.g. --host chisinau.md --host dgaurf.md",
    )
    parser.add_argument(
        "--seed-limit",
        type=int,
        default=None,
        help="Only use first N annex seeds (for quick tests)",
    )
    args = parser.parse_args()
    run_crawl(
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        only_hosts=args.hosts,
        seed_limit=args.seed_limit,
    )


if __name__ == "__main__":
    main()

