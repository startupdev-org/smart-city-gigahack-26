"""Decide whether a question belongs in the municipal document search."""

from __future__ import annotations

from typing import Any, Callable

from backend.ai.analyze import (
    identity_reply,
    looks_clearly_offtopic,
    looks_explicitly_municipal,
    looks_identity_question,
    looks_plausibly_municipal,
    offtopic_reply,
)

TopicClassifier = Callable[[str], dict[str, Any]]


def classify_scope(
    question: str,
    *,
    language: str = "ro",
    classifier: TopicClassifier | None = None,
) -> dict[str, Any]:
    """Reject clear off-topic questions and classify ambiguous ones by meaning.

    If the classifier is unavailable, search the corpus for plausible civic
    procedures. The later evidence gate still requires a supporting source.
    """
    if looks_identity_question(question):
        return {
            "summary": "Identitate asistent (fără căutare)",
            "relevant": False,
            "reason": "identity",
            "source": "heuristic",
            "reply": identity_reply(language),
            "kind": "identity",
        }
    if looks_clearly_offtopic(question):
        return {
            "summary": "În afara temei (heuristic)",
            "relevant": False,
            "reason": "clear_offtopic",
            "source": "heuristic",
            "reply": offtopic_reply(language),
            "kind": "offtopic",
        }
    if looks_explicitly_municipal(question):
        return {
            "summary": "Instituție și serviciu municipal identificate",
            "relevant": True,
            "reason": "named_authority_and_service",
            "source": "heuristic",
            "reply": None,
            "kind": "municipal",
        }

    def fallback(reason: str) -> dict[str, Any]:
        plausible = looks_plausibly_municipal(question)
        return {
            "summary": (
                "Clasificator indisponibil; verific corpusul"
                if plausible else "În afara temei (fallback)"
            ),
            "relevant": plausible,
            "reason": reason,
            "source": "fallback",
            "reply": None if plausible else offtopic_reply(language),
            "kind": "municipal" if plausible else "offtopic",
        }

    try:
        if classifier is None:
            from backend.ai.llm import get_llm_service

            classifier = get_llm_service().classify_topic_relevance
        judged = classifier(question)
        relevant = judged.get("relevant")
        if not isinstance(relevant, bool):
            return fallback(judged.get("reason") or "classifier_unavailable")
        return {
            "summary": "Pe temă (LLM)" if relevant else "În afara temei (LLM)",
            "relevant": relevant,
            "reason": judged.get("reason") or "",
            "source": judged.get("source") or "llm",
            "reply": None if relevant else offtopic_reply(language),
            "kind": "municipal" if relevant else "offtopic",
        }
    except Exception as exc:  # noqa: BLE001
        return fallback(f"classifier_unavailable:{exc.__class__.__name__}")
