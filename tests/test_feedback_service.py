import unittest

from app.services.feedback_service import (
    normalize_question,
    short_answer,
    source_ids_from_payload,
)


class FeedbackServiceUnitTests(unittest.TestCase):
    def test_normalize_question_repairs_spacing_and_case(self) -> None:
        normalized = normalize_question("  Aholi   punktlarida  Minimal ULUSH qancha?  ")
        self.assertEqual(normalized, "aholi punktlarida minimal ulush qancha?")

    def test_short_answer_prefers_summary_block(self) -> None:
        answer = "Batafsil: Uzun izoh.\nQisqa qilib aytganda: Minimal ulush 30%."
        self.assertEqual(short_answer(answer), "Minimal ulush 30%.")

    def test_source_ids_from_payload_is_stable(self) -> None:
        sources = [
            {"type": "clause", "shnq_code": "SHNQ 2.07.01-23", "clause_number": "7.5"},
            {"type": "table_row", "shnq_code": "SHNQ 2.07.01-23", "table_number": "9", "row_index": 3},
        ]
        ids = source_ids_from_payload(sources)
        self.assertEqual(ids[0], "clause:shnq2.07.01-23:7.5")
        self.assertEqual(ids[1], "table_row:shnq2.07.01-23:9:3")


if __name__ == "__main__":
    unittest.main()
