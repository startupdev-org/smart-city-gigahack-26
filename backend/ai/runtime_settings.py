"""Runtime LLM settings — switch local Ollama ↔ Groq without restarting the process."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from backend.config import get_settings

logger = logging.getLogger(__name__)

Provider = Literal["local", "groq"]

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parents[2] / "data" / "llm_runtime.json"

_DEFAULT_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "provider": s.llm_provider if s.llm_provider in ("local", "groq") else "local",
        "groq_model": s.groq_model or "openai/gpt-oss-120b",
        "local_model": s.ollama_model,
    }


def _read_file() -> dict[str, Any]:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read llm_runtime.json: %s", exc)
        return {}


def _write_file(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_llm_runtime() -> dict[str, Any]:
    s = get_settings()
    base = _defaults()
    with _LOCK:
        stored = _read_file()
    out = {**base, **{k: v for k, v in stored.items() if v is not None}}
    provider = out.get("provider") or "local"
    if provider not in ("local", "groq"):
        provider = "local"
    out["provider"] = provider
    out["groq_configured"] = bool((s.groq_api_key or "").strip())
    out["groq_base_url"] = s.groq_base_url.rstrip("/")
    out["ollama_base_url"] = s.ollama_base_url.rstrip("/")
    out["available_groq_models"] = list(_DEFAULT_GROQ_MODELS)
    if out["groq_model"] not in out["available_groq_models"]:
        out["available_groq_models"] = [out["groq_model"], *out["available_groq_models"]]
    # never expose full API key
    key = (s.groq_api_key or "").strip()
    out["groq_api_key_set"] = bool(key)
    out["groq_api_key_hint"] = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("set" if key else "")
    return out


def set_llm_runtime(
    *,
    provider: Provider | None = None,
    groq_model: str | None = None,
    local_model: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        data = {**_defaults(), **_read_file()}
        if provider is not None:
            if provider not in ("local", "groq"):
                raise ValueError("provider must be 'local' or 'groq'")
            if provider == "groq" and not (get_settings().groq_api_key or "").strip():
                raise ValueError(
                    "GROQ_API_KEY lipsește din .env — setează cheia înainte de a activa Groq."
                )
            data["provider"] = provider
        if groq_model is not None and groq_model.strip():
            data["groq_model"] = groq_model.strip()
        if local_model is not None and local_model.strip():
            data["local_model"] = local_model.strip()
        _write_file(
            {
                "provider": data["provider"],
                "groq_model": data["groq_model"],
                "local_model": data["local_model"],
            }
        )
    # invalidate LLM singleton so next call picks up new provider
    try:
        from backend.ai import llm as llm_mod

        llm_mod.reset_llm_service()
    except Exception:  # noqa: BLE001
        pass
    return get_llm_runtime()
