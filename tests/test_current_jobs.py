"""Current vacancies require a verified future deadline and the requested sector."""

import unittest
from datetime import date
from types import SimpleNamespace

from backend.ai.analyze import detect_intent, wants_current
from backend.ai.current_jobs import (
    application_deadlines,
    current_job_state,
    job_evidence_excerpt,
    job_hit_matches_sector,
    sector_in_question,
)
from backend.ai.scope import classify_scope


TODAY = date(2026, 9, 27)


def hit(text, *, title="Anunț concurs", url="https://ciocana.md/concurs"):
    return SimpleNamespace(document_title=title, document_url=url, content=text)


class CurrentJobTests(unittest.TestCase):
    def test_expired_deadlines_from_screenshot_are_not_open(self):
        for text in (
            "Termen de depunere a dosarelor 18 februarie 2026",
            "Termen de depunere a dosarelor 28 februarie 2026",
            "Termen de depunere a dosarelor 31 ianuarie 2026",
            "Termen de depunere a dosarelor 21 septembrie 2026",
            "Prelungirea termenului de depunere a dosarelor până la 18 februarie 2026",
        ):
            with self.subTest(text=text):
                self.assertEqual(current_job_state(hit(text), today=TODAY), "expired")

    def test_publication_year_or_no_deadline_cannot_prove_open(self):
        self.assertEqual(current_job_state(hit("Anunț concurs publicat în 2026"), today=TODAY), "unverified")
        self.assertEqual(current_job_state(hit("Termen de depunere a dosarelor: în curând"), today=TODAY), "unverified")
        self.assertEqual(current_job_state(hit("Termen de depunere 27 septembrie 2026"), today=TODAY), "unverified")

    def test_future_deadline_is_open(self):
        self.assertEqual(
            current_job_state(hit("Dosarele pot fi depuse până la data de 01.10.2026"), today=TODAY),
            "open",
        )
        self.assertEqual(application_deadlines("termen de depunere a dosarelor 18februarie2026"), [date(2026, 2, 18)])
        self.assertEqual(application_deadlines("Срок подачи документов: 1 октября 2026"), [date(2026, 10, 1)])

    def test_mixed_listing_deadlines_are_unverified(self):
        listing = "Termen de depunere 18 februarie 2026. Termen de depunere 1 octombrie 2026."
        self.assertEqual(current_job_state(hit(listing), today=TODAY), "unverified")
        self.assertEqual(current_job_state(hit("Prelungire. " + listing), today=TODAY), "unverified")

    def test_long_announcement_keeps_deadline_in_llm_excerpt(self):
        text = "Concurs specialist Ciocana. " + ("Descriere. " * 280)
        text += "Termenul de depunere a dosarelor: 1 octombrie 2026."
        excerpt = job_evidence_excerpt(text)
        self.assertLessEqual(len(excerpt), 2200)
        self.assertIn("1 octombrie 2026", excerpt)

    def test_ciocana_followup_routes_as_jobs(self):
        self.assertEqual(detect_intent("Există concursuri publice deschise acum?"), "concurs")
        self.assertTrue(wants_current("Există concursuri publice deschise acum?"))
        question = "dar funcții deschise la sectorul Ciocana?"
        self.assertEqual(detect_intent(question), "concurs")
        self.assertTrue(wants_current(question))
        self.assertEqual(sector_in_question(question), "ciocana")
        self.assertTrue(classify_scope(question, classifier=lambda _: self.fail("should not call model"))["relevant"])
        self.assertEqual(detect_intent("Какие конкурсы открыты сейчас?"), "concurs")
        self.assertTrue(wants_current("Какие конкурсы открыты сейчас?"))

    def test_other_sector_is_not_evidence_for_ciocana(self):
        buiucani = hit("Termen de depunere 1 octombrie 2026", title="Pretura sectorului Buiucani", url="https://buiucani.md/concurs")
        ciocana = hit("Termen de depunere 1 octombrie 2026", title="Pretura sectorului Ciocana")
        self.assertFalse(job_hit_matches_sector(buiucani, "ciocana"))
        self.assertTrue(job_hit_matches_sector(ciocana, "ciocana"))


if __name__ == "__main__":
    unittest.main()
