import unittest
from types import SimpleNamespace

from backend.ai.analyze import detect_intent
from backend.ai.conflicts import detect_document_conflicts


def hit(document_id, title, content, *, url=None, page=1):
    return SimpleNamespace(
        document_id=document_id,
        document_title=title,
        document_url=url or f"https://example.org/{document_id}",
        content=content,
        page=page,
    )


class ConflictTests(unittest.TestCase):
    def test_same_service_different_processing_times(self):
        self.assertEqual(detect_intent("Care este termenul pentru autorizația de construire?"), "deadline")
        docs = [
            hit(1, "Autorizația de construire", "Termen de eliberare autorizație de construire: 20 zile lucrătoare."),
            hit(2, "Pașaport autorizația de construire", "Termen de eliberare autorizație de construire: 30 zile lucrătoare."),
        ]
        result = detect_document_conflicts(docs, "Care este termenul pentru autorizația de construire?")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["field"], "duration_days")
        self.assertEqual(result[0]["left"]["value"], "20 zile")
        self.assertEqual(result[0]["right"]["value"], "30 zile")

    def test_unrelated_services_and_versions_do_not_conflict(self):
        permit = hit(1, "Autorizația de construire 2026", "Termen de eliberare autorizație de construire: 20 zile.")
        petition = hit(2, "Petiții", "Termen de soluționare petiții: 30 zile.")
        old_permit = hit(3, "Autorizația de construire 2024", "Termen de eliberare autorizație de construire: 30 zile.")
        question = "Care este termenul pentru autorizația de construire?"
        self.assertEqual(detect_document_conflicts([permit, petition], question), [])
        self.assertEqual(detect_document_conflicts([permit, old_permit], question), [])
        self.assertEqual(detect_document_conflicts([permit, old_permit], "Care este termenul?"), [])

    def test_fee_conflict(self):
        docs = [
            hit(1, "Certificat de urbanism", "Taxa pentru certificatul de urbanism este 50 lei."),
            hit(2, "Certificat de urbanism", "Taxa pentru certificatul de urbanism este 75 lei."),
        ]
        result = detect_document_conflicts(docs, "Cât costă certificatul de urbanism?")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["field"], "fee")
        self.assertEqual(result[0]["left"]["value"], "50 lei")
        self.assertEqual(
            len(detect_document_conflicts(docs, "Care este taxa pentru certificatul de urbanism?")),
            1,
        )

    def test_ambiguous_document_and_jobs_are_not_flagged(self):
        mixed = hit(1, "Autorizația de construire", "Termen de eliberare: 20 zile. În regim urgent: 10 zile.")
        normal = hit(2, "Autorizația de construire", "Termen de eliberare: 30 zile.")
        self.assertEqual(
            detect_document_conflicts([mixed, normal], "Care este termenul pentru autorizația de construire?"),
            [],
        )
        self.assertEqual(
            detect_document_conflicts([normal, hit(3, "Concurs public", "Termen de depunere: 10 zile.")], "Care este termenul pentru concurs?"),
            [],
        )

    def test_different_day_units_are_not_compared(self):
        docs = [
            hit(1, "Autorizația de construire", "Termen de eliberare autorizație de construire: 20 zile lucrătoare."),
            hit(2, "Autorizația de construire", "Termen de eliberare autorizație de construire: 30 zile calendaristice."),
        ]
        self.assertEqual(
            detect_document_conflicts(docs, "Care este termenul pentru autorizația de construire?"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
