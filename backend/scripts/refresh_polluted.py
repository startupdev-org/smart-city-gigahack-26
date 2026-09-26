"""Re-fetch HTML documents whose content is chrome-polluted (menus/sidebars)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import or_

from backend.crawler.allowlist import normalize_url, registrable_host
from backend.crawler.fetcher import Fetcher
from backend.crawler.html_parser import extract_html
from backend.crawler.ingest import ensure_source, ingest_text_document
from backend.db.database import SessionLocal
from backend.db.models import Document

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("refresh_polluted")


def main() -> None:
    db = SessionLocal()
    docs = (
        db.query(Document)
        .filter(
            or_(
                Document.content.ilike("%DISPOZI%PRETORULUI%"),
                Document.content.ilike("%Căutați pe Internet%"),
                Document.content.ilike("%Cautati pe Internet%"),
                Document.title.ilike("%cariera%"),
            ),
            Document.url.isnot(None),
            Document.mime_type == "text/html",
        )
        .limit(200)
        .all()
    )
    logger.info("Candidates: %d", len(docs))
    fetcher = Fetcher()
    ok = 0
    for d in docs:
        url = (d.url or "").strip()
        if not url.startswith("http"):
            continue
        res = fetcher.fetch(url)
        if not res or not res.body or res.status >= 400:
            logger.warning("Fail %s (%s)", url, getattr(res, "status", None))
            continue
        final = normalize_url(res.final_url)
        title, text, _ = extract_html(final, res.body)
        host = registrable_host(final)
        root = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
        src = ensure_source(
            db,
            url=root,
            name=host,
            category="refresh",
            priority="P1",
            type_="portal",
        )
        ingest_text_document(
            db,
            source=src,
            title=title,
            url=final,
            text=text,
            mime_type="text/html",
        )
        db.commit()
        ok += 1
        logger.info("Refreshed [%d] %s (%d chars)", ok, title[:70], len(text))
    logger.info("Done. Refreshed %d / %d", ok, len(docs))
    db.close()


if __name__ == "__main__":
    main()
