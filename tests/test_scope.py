"""Scope routing examples that must not depend on exact municipal wording."""

import unittest

from backend.ai.scope import classify_scope


class ScopeTests(unittest.TestCase):
    def test_implicit_construction_paperwork_reaches_semantic_classifier(self):
        asked = []

        def classify(question):
            asked.append(question)
            return {"relevant": True, "reason": "building paperwork", "source": "llm"}

        for question in (
            "What documents do I need to build a new house?",
            "Ce acte îmi trebuie când construiesc o casă nouă?",
            "Какие документы нужны, чтобы построить новый дом?",
        ):
            with self.subTest(question=question):
                result = classify_scope(question, classifier=classify)
                self.assertTrue(result["relevant"])
                self.assertEqual(result["source"], "llm")
        self.assertEqual(len(asked), 3)

    def test_city_name_alone_does_not_force_acceptance(self):
        result = classify_scope(
            "Who won the football match in Chișinău?",
            classifier=lambda _: {"relevant": False, "reason": "sports", "source": "llm"},
        )
        self.assertFalse(result["relevant"])

    def test_clear_offtopic_is_rejected_without_model_call(self):
        def unexpected(_):
            self.fail("classifier should not run for clear off-topic questions")

        result = classify_scope("What is the weather in Chișinău?", classifier=unexpected)
        self.assertFalse(result["relevant"])
        self.assertEqual(result["source"], "heuristic")

    def test_named_authority_and_service_are_accepted_without_model_call(self):
        def unexpected(_):
            self.fail("classifier should not run for an explicit municipal request")

        result = classify_scope("Care este contactul DGAURF?", classifier=unexpected)
        self.assertTrue(result["relevant"])
        self.assertEqual(result["reason"], "named_authority_and_service")

    def test_pizza_shop_permit_is_not_rejected_for_pizza_keyword(self):
        result = classify_scope(
            "What permit do I need for a pizza shop?",
            classifier=lambda _: {"relevant": True, "reason": "permit", "source": "llm"},
        )
        self.assertTrue(result["relevant"])

    def test_classifier_failure_defers_to_corpus_evidence(self):
        def unavailable(_):
            raise OSError("model offline")

        for classifier in (
            unavailable,
            lambda _: {"relevant": None, "reason": "classifier_error"},
            lambda _: {"relevant": "false", "reason": "invalid_json_type"},
        ):
            with self.subTest(classifier=classifier):
                result = classify_scope(
                    "Ce acte îmi trebuie când construiesc o casă?",
                    classifier=classifier,
                )
                self.assertTrue(result["relevant"])
                self.assertEqual(result["source"], "fallback")

    def test_classifier_failure_does_not_accept_city_name_alone(self):
        def unavailable(_):
            raise OSError("model offline")

        result = classify_scope(
            "Who won the football match in Chișinău?", classifier=unavailable
        )
        self.assertFalse(result["relevant"])
        self.assertEqual(result["source"], "fallback")


if __name__ == "__main__":
    unittest.main()
