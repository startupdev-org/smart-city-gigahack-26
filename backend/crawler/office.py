from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def extract_docx(body: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(body))
    parts: list[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def extract_xlsx(body: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        parts.append(f"## Sheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if vals:
                parts.append(" | ".join(vals))
    return "\n".join(parts)


def extract_doc_legacy(body: bytes) -> str:
    """Best-effort for old .doc — often fails; return empty if unsupported."""
    logger.warning("Legacy .doc extraction not fully supported; skipping binary parse")
    return ""
