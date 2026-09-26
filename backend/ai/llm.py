from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import httpx

from backend.ai.prompts import (
    STRUCTURED_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_stream_prompt,
    build_user_prompt,
)
from backend.ai.runtime_settings import get_llm_runtime
from backend.config import get_settings

logger = logging.getLogger(__name__)

_LLM_SINGLETON: "LLMService | None" = None


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json(text: str) -> dict[str, Any]:
    text = _strip_think(text or "")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))


def _truncate(user: str, limit: int = 12000) -> str:
    if len(user) > limit:
        return user[:limit] + "\n…(truncated)"
    return user


class LLMService:
    """CivicAI LLM — Ollama (local) or Groq Cloud (OpenAI-compatible chat/completions)."""

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        settings = get_settings()
        runtime = get_llm_runtime()
        self.provider = runtime.get("provider") or "local"
        self.local_base = settings.ollama_base_url.rstrip("/")
        self.local_model = runtime.get("local_model") or settings.ollama_model
        self.groq_base = settings.groq_base_url.rstrip("/")
        self.groq_key = (settings.groq_api_key or "").strip()
        self.groq_model = runtime.get("groq_model") or settings.groq_model
        self.model = self.groq_model if self.provider == "groq" else self.local_model

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
        }

    # ── Ollama payloads ──────────────────────────────────────────────
    def _ollama_payload(self, *, system: str, user: str, stream: bool) -> dict[str, Any]:
        return {
            "model": self.local_model,
            "stream": stream,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_ctx": 3072,
                "num_predict": 1200,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": _truncate(user, 14000)},
            ],
        }

    # ── Groq OpenAI-compatible payloads ──────────────────────────────
    def _groq_headers(self) -> dict[str, str]:
        if not self.groq_key:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        return {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }

    def _groq_payload(
        self, *, system: str, user: str, stream: bool, max_tokens: int = 1600
    ) -> dict[str, Any]:
        return {
            "model": self.groq_model,
            "stream": stream,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": _truncate(user, 20000)},
            ],
        }

    def _chat_once(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        if self.provider == "groq":
            payload = self._groq_payload(
                system=system, user=user, stream=False, max_tokens=max_tokens
            )
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    f"{self.groq_base}/chat/completions",
                    headers=self._groq_headers(),
                    json=payload,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"Groq {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return _strip_think(
                    (((data.get("choices") or [{}])[0].get("message") or {}).get("content"))
                    or ""
                )
        payload = self._ollama_payload(system=system, user=user, stream=False)
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(f"{self.local_base}/api/chat", json=payload)
            if resp.status_code >= 400:
                payload.pop("think", None)
                payload["options"]["num_ctx"] = 1536
                resp = client.post(f"{self.local_base}/api/chat", json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(resp.text[:200])
            msg = resp.json().get("message") or {}
            return _strip_think(msg.get("content") or msg.get("thinking") or "")

    def generate_structured(
        self,
        question: str,
        evidence_blocks: list[str],
        topic_links: list[str],
        *,
        language_meta: dict | None = None,
    ) -> dict[str, Any]:
        prompt = build_user_prompt(
            question, evidence_blocks, topic_links, language_meta=language_meta
        )
        try:
            content = self._chat_once(
                system=STRUCTURED_SYSTEM_PROMPT, user=prompt, max_tokens=1400
            )
            data = _extract_json(content)
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM failed (%s): %s", self.provider, exc)
            return {
                "status": "missing",
                "answer": (
                    "Nu am putut genera răspunsul LLM momentan. "
                    "Sursele găsite sunt listate mai jos — verificați pasajele."
                ),
                "refs": [],
                "confidence": "low",
                "language": "ro",
                "error": str(exc)[:200],
            }

        if "status" not in data:
            data["status"] = "missing"
        if "answer" not in data:
            data["answer"] = ""
        if "refs" not in data:
            data["refs"] = []
        data.pop("sources", None)
        return data

    def classify_topic_relevance(self, question: str) -> dict[str, Any]:
        """Cheap first-pass: is this a Chișinău municipal question worth RAG?"""
        user = (
            "You are a gatekeeper for CivicAI, a Chișinău City Hall assistant.\n"
            "Decide if the user question is ABOUT municipal / public-administration topics "
            "for Chișinău (permits, contacts, preturi, jobs/concursuri, taxes, schools under "
            "municipality, urbanism, services, official announcements, etc.).\n"
            "Mark OFF-TOPIC if: chit-chat, jokes, identity of the AI, general world knowledge, "
            "coding, recipes, other cities only, homework unrelated to the municipality, "
            "personal advice with no municipal angle.\n"
            "Return ONLY JSON: "
            '{"relevant": true|false, "reason": "short"}\n\n'
            f"Question: {question}"
        )
        try:
            content = self._chat_once(
                system="Reply with JSON only. relevant=false when not Chișinău municipal.",
                user=user,
                max_tokens=80,
            )
            data = _extract_json(content)
            relevant = bool(data.get("relevant"))
            reason = str(data.get("reason") or "")[:160]
            return {"relevant": relevant, "reason": reason, "source": "llm"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("classify_topic_relevance failed: %s", exc)
            # Fail open for municipal-looking questions; fail closed only if empty
            return {
                "relevant": bool((question or "").strip()),
                "reason": "classifier_error",
                "source": "fallback",
                "error": str(exc)[:120],
            }

    def expand_search_queries(self, question: str, *, max_queries: int = 4) -> list[str]:
        user = (
            "Given this Chișinău municipal Q&A question, propose alternative search "
            "queries that might find the answer in an official document corpus.\n"
            "Return ONLY a JSON array of 2-4 short search strings "
            "(Romanian preferred for municipal docs; include EN/RU variants if useful).\n"
            f"Question: {question}"
        )
        try:
            content = self._chat_once(
                system="You expand search queries for municipal RAG. Reply with JSON array only.",
                user=user,
                max_tokens=200,
            )
            data = _extract_json(content) if content.strip().startswith("{") else None
            if isinstance(data, dict) and "queries" in data:
                arr = data["queries"]
            else:
                m = re.search(r"\[[\s\S]*\]", content)
                arr = json.loads(m.group(0)) if m else []
            out: list[str] = []
            for item in arr or []:
                s = str(item).strip()
                if s and s.lower() != question.strip().lower() and s not in out:
                    out.append(s[:160])
                if len(out) >= max_queries:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("expand_search_queries failed: %s", exc)
            return []

    def stream_answer(
        self,
        question: str,
        evidence_blocks: list[str],
        *,
        language_meta: dict | None = None,
    ) -> Iterator[str]:
        prompt = build_stream_prompt(
            question, evidence_blocks, language_meta=language_meta
        )
        try:
            if self.provider == "groq":
                yield from self._stream_groq(SYSTEM_PROMPT, prompt)
            else:
                yield from self._stream_ollama(SYSTEM_PROMPT, prompt)
        except OSError as exc:
            logger.warning("LLM stream OSError (%s); falling back to non-stream", exc)
            yield from self._nonstream_tokens(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM stream failed (%s): %s", self.provider, exc)
            try:
                yield from self._nonstream_tokens(prompt)
            except Exception:  # noqa: BLE001
                yield (
                    "Nu am putut genera răspunsul LLM momentan. "
                    "Încercați din nou în câteva secunde."
                )

    def _stream_groq(self, system: str, user: str) -> Iterator[str]:
        payload = self._groq_payload(
            system=system, user=user, stream=True, max_tokens=1600
        )
        with httpx.Client(timeout=180.0) as client:
            with client.stream(
                "POST",
                f"{self.groq_base}/chat/completions",
                headers=self._groq_headers(),
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="ignore")[:300]
                    raise RuntimeError(f"Groq stream {resp.status_code}: {body}")
                yield from self._iter_openai_sse(resp)

    def _stream_ollama(self, system: str, user: str) -> Iterator[str]:
        payload = self._ollama_payload(system=system, user=user, stream=True)
        with httpx.Client(timeout=300.0) as client:
            with client.stream(
                "POST", f"{self.local_base}/api/chat", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="ignore")[:300]
                    payload.pop("think", None)
                    payload["options"]["num_ctx"] = 1024
                    with client.stream(
                        "POST", f"{self.local_base}/api/chat", json=payload
                    ) as resp2:
                        if resp2.status_code >= 400:
                            raise RuntimeError(
                                body
                                or resp2.read().decode("utf-8", errors="ignore")[:200]
                            )
                        yield from self._iter_ollama_tokens(resp2)
                    return
                yield from self._iter_ollama_tokens(resp)

    def _nonstream_tokens(self, prompt: str) -> Iterator[str]:
        content = self._chat_once(system=SYSTEM_PROMPT, user=prompt, max_tokens=1600)
        if content:
            yield content

    def _iter_ollama_tokens(self, resp) -> Iterator[str]:
        buf = ""
        for raw in resp.iter_bytes():
            if not raw:
                continue
            buf += raw.decode("utf-8", errors="ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                token = msg.get("content") or ""
                if token:
                    yield token
                if chunk.get("done"):
                    return
        line = buf.strip()
        if line:
            try:
                chunk = json.loads(line)
                msg = chunk.get("message") or {}
                token = msg.get("content") or ""
                if token:
                    yield token
            except json.JSONDecodeError:
                pass

    def _iter_openai_sse(self, resp) -> Iterator[str]:
        """Parse OpenAI/Groq SSE: lines like `data: {...}` / `data: [DONE]`."""
        buf = ""
        for raw in resp.iter_bytes():
            if not raw:
                continue
            buf += raw.decode("utf-8", errors="ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    token = delta.get("content") or ""
                    if token:
                        yield token
                    if choices[0].get("finish_reason"):
                        return


def reset_llm_service() -> None:
    global _LLM_SINGLETON
    _LLM_SINGLETON = None


def get_llm_service() -> LLMService:
    global _LLM_SINGLETON
    if _LLM_SINGLETON is None:
        _LLM_SINGLETON = LLMService()
    else:
        # keep in sync if runtime file changed elsewhere
        _LLM_SINGLETON.reload()
    return _LLM_SINGLETON
