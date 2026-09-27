import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.ai.conversation_cache import find_prior_answer


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
QUESTION = "Ce autorizații îmi trebuie pentru construcție?"


def pair(question=QUESTION, *, status="supported", age_hours=1, sources=True):
    user = SimpleNamespace(role="user", content=question)
    assistant = SimpleNamespace(
        role="assistant",
        content="Ai nevoie de autorizația de construire. [1]",
        status=status,
        sources_json=json.dumps([{"url": "https://example.org/permit.pdf"}]) if sources else None,
        created_at=NOW - timedelta(hours=age_hours),
    )
    return [user, assistant]


class ConversationCacheTests(unittest.TestCase):
    def test_reuses_recent_repeat_with_source(self):
        messages = pair()
        self.assertIs(
            find_prior_answer(messages, "ce AUTORIZATII imi trebuie pentru constructie", now=NOW),
            messages[1],
        )

    def test_does_not_reuse_missing_unsourced_stale_or_reused_answer(self):
        for kwargs in (
            {"status": "missing"},
            {"status": "reused"},
            {"sources": False},
            {"age_hours": 25},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(find_prior_answer(pair(**kwargs), QUESTION, now=NOW))

    def test_changed_or_time_sensitive_question_uses_normal_pipeline(self):
        previous = pair()
        for question in (
            "Ce autorizații îmi trebuie pentru construcție în Ciocana?",
            "Există concursuri publice deschise acum?",
            "Care este termenul pentru autorizația de construire?",
            "Cât costă certificatul de urbanism?",
            "Care sunt ultimele autorizații pentru construcție?",
            "Dar ce autorizații îmi trebuie pentru construcție?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(find_prior_answer(previous, question, now=NOW))

    def test_fee_and_duration_answers_are_always_rechecked(self):
        for question in (
            "Cât costă certificatul de urbanism?",
            "Care este termenul pentru autorizația de construire?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(find_prior_answer(pair(question), question, now=NOW))

    def test_never_pairs_nonadjacent_messages(self):
        messages = [pair()[0], pair("Ce acte trebuie pentru urbanism?")[0], pair()[1]]
        self.assertIsNone(find_prior_answer(messages, QUESTION, now=NOW))


if __name__ == "__main__":
    unittest.main()
