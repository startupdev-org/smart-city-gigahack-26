from __future__ import annotations

import re

# Soft-404 / dead page markers (RO / RU / EN)
_SOFT_404_RE = re.compile(
    r"(?:"
    r"404(\s*not\s*found|\s*error)?"
    r"|page\s+not\s+found"
    r"|not\s+found"
    r"|pagina\s+(nu\s+a\s+fost\s+g[aă]sit[aă]|lips[eă]ște|inexistent[aă])"
    r"|nu\s+a\s+fost\s+g[aă]sit[aă]"
    r"|pagina\s+solicitat[aă]\s+nu\s+exist[aă]"
    r"|erori?\s*404"
    r"|страница\s+не\s+найдена"
    r"|не\s+найдена"
    r"|документ\s+не\s+найден"
    r"|oops[!.,]?\s*nothing\s+was\s+found"
    r"|this\s+page\s+doesn.?t\s+exist"
    r"|conteúdo\s+não\s+encontrado"
    r")",
    re.IGNORECASE,
)

_EMPTYISH_TITLES = {
    "404",
    "not found",
    "error",
    "eroare",
    "pagina nu a fost găsită",
    "страница не найдена",
}


def is_http_error(status: int) -> bool:
    return status >= 400


def is_soft_404(*, status: int, title: str = "", text: str = "", url: str = "") -> bool:
    """Detect dead pages even when server returns 200 with an error template."""
    if status >= 400:
        return True
    t = (title or "").strip().lower()
    if t in _EMPTYISH_TITLES or t.startswith("404"):
        return True
    # Check early body (error pages are short / front-loaded)
    head = f"{title}\n{(text or '')[:2500]}"
    if _SOFT_404_RE.search(head):
        # Avoid false positives on real docs that merely mention "404" once in a table
        hits = len(_SOFT_404_RE.findall(head))
        body_len = len((text or "").strip())
        if hits >= 2 or body_len < 400 or t.startswith("404") or "not found" in t:
            return True
        if body_len < 800 and _SOFT_404_RE.search(title or ""):
            return True
    return False
