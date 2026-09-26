"""Startup / LLM-mode banners and selective local model warming."""

from __future__ import annotations

import logging
import sys
import threading

import httpx

logger = logging.getLogger(__name__)

_RESET = "\033[0m"
_BOLD = "\033[1m"
_WHITE_ON_BLUE = "\033[97;44m"  # LOCAL ACTIVE
_WHITE_ON_RED = "\033[97;41m"  # LOCAL INACTIVE (API)


def _enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL
    except Exception:  # noqa: BLE001
        pass


def print_llm_mode_banner(*, provider: str, model: str, extra: str = "") -> None:
    """Big colored block: blue = local active, red = local inactive (API)."""
    _enable_windows_ansi()
    local_on = (provider or "").lower() == "local"
    if local_on:
        title = " LOCAL ACTIVE "
        detail = f" Ollama · {model} "
        color = _WHITE_ON_BLUE
    else:
        title = " LOCAL INACTIVE "
        detail = f" API Groq · {model} "
        color = _WHITE_ON_RED
    if extra:
        detail = f"{detail}· {extra} "
    inner_w = max(52, len(title.strip()) + 4, len(detail.strip()) + 4)
    line = "=" * inner_w
    pad_title = title.center(inner_w)
    pad_detail = detail.center(inner_w)
    # Prefer UTF-8 stdout on Windows so colors + box render
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    block = (
        f"\n{_BOLD}{color}"
        f"  {line}\n"
        f"  {pad_title}\n"
        f"  {pad_detail}\n"
        f"  {line}"
        f"{_RESET}\n"
    )
    try:
        print(block, flush=True)
    except UnicodeEncodeError:
        plain = f"\n*** {title.strip()} — {detail.strip()} ***\n"
        print(plain, flush=True)
    # also log without ANSI for files
    logger.info(
        "LLM mode: %s · model=%s%s",
        "LOCAL ACTIVE" if local_on else "LOCAL INACTIVE (API)",
        model,
        f" · {extra}" if extra else "",
    )


def warm_local_stack(*, include_rag: bool = True, include_ollama: bool = True) -> None:
    """Load local heavy models (embeddings/reranker) + optional Ollama ping."""
    if include_rag:
        try:
            from backend.ai.embeddings import get_embedding_service
            from backend.ai.reranker import get_reranker_service

            logger.info("Loading local RAG models (embedding + reranker)…")
            get_embedding_service().warm()
            get_reranker_service().warm()
            logger.info("Local RAG models ready")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local RAG warm failed: %s", exc)

    if include_ollama:
        try:
            from backend.ai.runtime_settings import get_llm_runtime
            from backend.config import get_settings

            rt = get_llm_runtime()
            base = get_settings().ollama_base_url.rstrip("/")
            model = rt.get("local_model") or get_settings().ollama_model
            with httpx.Client(timeout=8.0) as client:
                r = client.get(f"{base}/api/tags")
                r.raise_for_status()
            logger.info("Ollama reachable at %s (model=%s)", base, model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama not ready yet: %s", exc)


def warm_local_stack_async(**kwargs: bool) -> None:
    threading.Thread(target=lambda: warm_local_stack(**kwargs), daemon=True).start()
