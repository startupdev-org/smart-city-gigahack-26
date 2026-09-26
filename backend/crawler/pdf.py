from __future__ import annotations

import io
import logging

from pypdf import PdfReader

logger = logging.getLogger(__name__)


def extract_pdf(body: bytes) -> tuple[str, list[str]]:
    """
    Returns (title_guess, pages_text).
    Falls back to OCR (pytesseract) when a page has no text layer.
    """
    reader = PdfReader(io.BytesIO(body))
    title = ""
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title).strip()

    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF page extract failed: %s", exc)
            text = ""
        text = text.strip()
        if len(text) < 20:
            ocr = _ocr_page(body, i)
            if ocr:
                text = ocr
        pages.append(text)
    return title, pages


def _ocr_page(pdf_bytes: bytes, page_number: int) -> str:
    """Optional OCR — requires pytesseract + pdf2image + Poppler + Tesseract installed."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        return ""

    try:
        images = convert_from_bytes(
            pdf_bytes, first_page=page_number, last_page=page_number, dpi=200
        )
        if not images:
            return ""
        # Romanian + Russian municipal docs
        return pytesseract.image_to_string(images[0], lang="ron+rus+eng").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed page %s: %s", page_number, exc)
        return ""
