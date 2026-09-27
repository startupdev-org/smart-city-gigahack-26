"""Regression cases for model replies that contradict a supported evidence gate."""

import unittest

from backend.ai.answer_status import answer_claims_missing


class AnswerStatusTests(unittest.TestCase):
    def test_uncited_missing_answers(self):
        for answer in (
            "În informațiile disponibile nu s-a găsit detalii despre autorizațiile necesare pentru construcție.",
            "Nu s-au găsit detalii în documentele disponibile.",
            "Informația nu a fost identificată în corpusul municipal disponibil.",
            "No relevant information was found.",
            "Информация не найдена в документах.",
            "missing",
        ):
            with self.subTest(answer=answer):
                self.assertTrue(answer_claims_missing(answer))

    def test_factual_answers_are_not_misses(self):
        for answer in (
            "Nu există taxă pentru această autorizație [1].",
            "Nu există informații despre o taxă nouă; regulamentul spune că procedura este gratuită [1].",
            "Nu am găsit taxa în anexa 1, dar anexa 2 indică 50 lei [2].",
            "Cererea se depune la DGAURF împreună cu actele [1].",
        ):
            with self.subTest(answer=answer):
                self.assertFalse(answer_claims_missing(answer))


if __name__ == "__main__":
    unittest.main()
