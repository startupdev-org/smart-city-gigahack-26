import unittest

from backend.ai.followups import contextualize_question


class FollowupTests(unittest.TestCase):
    def test_short_sector_followup_inherits_current_job_topic(self):
        self.assertEqual(
            contextualize_question(
                "Dar în sectorul Ciocana?",
                "Există concursuri publice deschise acum?",
            ),
            "Există concursuri publice deschise acum în sectorul Ciocana?",
        )
        self.assertEqual(
            contextualize_question(
                "Dar la Ciocana?",
                "Există concursuri publice deschise acum în Buiucani?",
            ),
            "Există concursuri publice deschise acum în sectorul Ciocana?",
        )

    def test_explicit_or_new_question_does_not_inherit_prior_topic(self):
        previous = "Există concursuri publice deschise acum?"
        for question in (
            "dar funcții deschise la sectorul Ciocana?",
            "Cum obțin o autorizație de construire?",
            "Dar ce acte sunt necesare?",
        ):
            with self.subTest(question=question):
                self.assertEqual(contextualize_question(question, previous), question)

    def test_english_followup_keeps_english(self):
        self.assertEqual(
            contextualize_question("What about Ciocana?", "Are there job openings now?"),
            "What job openings are available now in Ciocana sector?",
        )


if __name__ == "__main__":
    unittest.main()
