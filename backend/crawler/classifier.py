from __future__ import annotations

from urllib.parse import urlparse

from backend.crawler.allowlist import DOC_EXTENSIONS
from backend.crawler.fetcher import FetchResult


def classify(result: FetchResult) -> str:
    """Return: html | pdf | docx | doc | xlsx | xls | other_doc | skip"""
    ctype = (result.content_type or "").lower()
    path = urlparse(result.final_url).path.lower()

    if "text/html" in ctype or path.endswith((".html", ".htm", ".php", ".aspx")) or (
        not any(path.endswith(e) for e in DOC_EXTENSIONS) and ctype.startswith("text/")
    ):
        # if body looks like HTML
        head = result.body[:200].lstrip().lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html") or b"<html" in head:
            return "html"
        if "text/html" in ctype:
            return "html"

    if "pdf" in ctype or path.endswith(".pdf"):
        return "pdf"
    if (
        "wordprocessingml" in ctype
        or path.endswith(".docx")
        or "application/vnd.openxmlformats-officedocument.wordprocessingml" in ctype
    ):
        return "docx"
    if path.endswith(".doc") or "msword" in ctype:
        return "doc"
    if path.endswith(".xlsx") or "spreadsheetml" in ctype:
        return "xlsx"
    if path.endswith(".xls") or "excel" in ctype:
        return "xls"
    if any(path.endswith(e) for e in DOC_EXTENSIONS):
        return "other_doc"
    # fallback: try html if printable
    if b"<html" in result.body[:2000].lower():
        return "html"
    return "skip"
