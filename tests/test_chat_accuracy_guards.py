import unittest

from app.rag.reference_parser import ExactReference
from app.services.chat_service import (
    RetrievalItem,
    _clean_fewshot_text,
    _extract_doc_choice_from_text,
    _filter_items_by_query_anchors,
    _has_fewshot_mojibake,
    _is_route_ambiguous,
    _pick_exact_clause_candidate,
    _stem_query_token,
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

    def test_extract_doc_choice_from_json(self) -> None:
        picked = _extract_doc_choice_from_text(
            '{"code":"SHNQ 2.01.05-24"}',
            ["SHNQ 2.01.05-24", "SHNQ 2.04.01-22"],
        )
        self.assertEqual(picked, "SHNQ 2.01.05-24")

    def test_route_ambiguity_detects_close_scores(self) -> None:
        debug = {
            "scores": [
                {"code": "SHNQ 2.01.05-24", "score": 0.28},
                {"code": "SHNQ 2.04.01-22", "score": 0.27},
            ]
        }
        self.assertTrue(_is_route_ambiguous(debug))

    def test_stem_query_token_reduces_common_suffixes(self) -> None:
        self.assertEqual(_stem_query_token("hojatxonasidan"), "hojatxona")
        self.assertEqual(_stem_query_token("binosigacha"), "bino")

    def test_filter_items_by_query_anchors_prefers_matching_object(self) -> None:
        items = [
            RetrievalItem(
                kind="clause",
                score=0.8,
                title="x",
                snippet="Turar joy xonalarida derazadan 1 m masofa...",
                shnq_code="SHNQ 2.01.05-24",
                semantic_score=0.55,
                keyword_score=0.37,
            ),
            RetrievalItem(
                kind="clause",
                score=0.72,
                title="y",
                snippet="Hovli hojatxonasi turar joy binosidan 12 m masofada joylashtiriladi.",
                shnq_code="SHNQ 2.07.01-23",
                semantic_score=0.31,
                keyword_score=0.44,
            ),
        ]
        filtered = _filter_items_by_query_anchors(
            "Hovli hojatxonasidan turar joy binosigacha masofa qancha bo'lishi kerak?",
            items,
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].shnq_code, "SHNQ 2.07.01-23")


if __name__ == "__main__":
    unittest.main()
