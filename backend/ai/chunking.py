from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


def sha256_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def approx_token_count(text: str) -> int:
    # Rough heuristic for RO/RU: ~0.75 words per token
    words = len(text.split())
    return max(1, int(words / 0.75))


@dataclass
class TextChunk:
    content: str
    page: int | None = None
    section: str | None = None
    token_count: int = 0


def chunk_text(
    text: str,
    *,
    chunk_size_tokens: int = 650,
    overlap_tokens: int = 100,
    page: int | None = None,
    section: str | None = None,
) -> list[TextChunk]:
    """Split text into overlapping chunks by approximate token size."""
    cleaned = re.sub(r"\r\n?", "\n", text).strip()
    if not cleaned:
        return []

    # Prefer splitting on paragraph boundaries, then sentences.
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if approx_token_count(para) <= chunk_size_tokens:
            units.append(para)
        else:
            sentences = re.split(r"(?<=[\.\!\?…])\s+", para)
            units.extend(s.strip() for s in sentences if s.strip())

    chunks: list[TextChunk] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        body = "\n\n".join(current).strip()
        chunks.append(
            TextChunk(
                content=body,
                page=page,
                section=section,
                token_count=approx_token_count(body),
            )
        )
        # overlap: keep trailing units
        if overlap_tokens <= 0:
            current = []
            current_tokens = 0
            return
        keep: list[str] = []
        keep_tokens = 0
        for unit in reversed(current):
            t = approx_token_count(unit)
            if keep_tokens + t > overlap_tokens and keep:
                break
            keep.insert(0, unit)
            keep_tokens += t
        current = keep
        current_tokens = keep_tokens

    for unit in units:
        t = approx_token_count(unit)
        if current and current_tokens + t > chunk_size_tokens:
            flush()
        current.append(unit)
        current_tokens += t

    flush()
    return chunks


def chunk_pages(
    pages: list[str],
    *,
    chunk_size_tokens: int = 650,
    overlap_tokens: int = 100,
) -> list[TextChunk]:
    out: list[TextChunk] = []
    for i, page_text in enumerate(pages, start=1):
        out.extend(
            chunk_text(
                page_text,
                chunk_size_tokens=chunk_size_tokens,
                overlap_tokens=overlap_tokens,
                page=i,
            )
        )
    return out
