import unittest

from app.rag.reference_parser import ExactReference
from app.services.chat_service import (
    RetrievalItem,
    _clean_fewshot_text,
    _has_fewshot_mojibake,
    _pick_exact_clause_candidate,
)
from app.utils.text_fix import repair_mojibake


class ChatAccuracyGuardsTests(unittest.TestCase):
    def test_repair_mojibake_handles_k_markers(self) -> None:
        fixed = repair_mojibake("o\u041A\u00BBrnatish")
        self.assertEqual(fixed, "o\u02bbrnatish")

    def test_clean_fewshot_text_removes_mojibake(self) -> None:
        cleaned = _clean_fewshot_text("  g\u041A\u0458isht devor  ")
        self.assertEqual(cleaned, "g\u02bbisht devor")
        self.assertFalse(_has_fewshot_mojibake(cleaned))

    def test_pick_exact_clause_candidate_matches_clause_and_doc(self) -> None:
        ref = ExactReference(document_codes=["SHNQ 2.01.05-24"], clause_numbers=["3.4"])
        items = [
            RetrievalItem(
                kind="clause",
                score=0.33,
                title="x",
                snippet="A",
                shnq_code="SHNQ 2.01.05-24",
                clause_number="3.4",
                clause_id="1",
            ),
            RetrievalItem(
                kind="clause",
                score=0.91,
                title="y",
                snippet="B",
                shnq_code="SHNQ 2.07.01-23",
                clause_number="3.4",
                clause_id="2",
            ),
        ]
        picked = _pick_exact_clause_candidate(items, ref, requested_doc_code="SHNQ 2.01.05-24")
        self.assertIsNotNone(picked)
        self.assertEqual((picked.clause_id or ""), "1")

    def test_pick_exact_clause_candidate_none_when_no_clause_match(self) -> None:
        ref = ExactReference(document_codes=["SHNQ 2.01.05-24"], clause_numbers=["9.9"])
        items = [
            RetrievalItem(
                kind="clause",
                score=0.5,
                title="x",
                snippet="A",
                shnq_code="SHNQ 2.01.05-24",
                clause_number="3.4",
                clause_id="1",
            ),
        ]
        picked = _pick_exact_clause_candidate(items, ref, requested_doc_code="SHNQ 2.01.05-24")
        self.assertIsNone(picked)


if __name__ == "__main__":
    unittest.main()
