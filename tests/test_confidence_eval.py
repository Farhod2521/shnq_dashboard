import unittest
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "app" not in sys.modules:
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(ROOT / "app")]
    sys.modules["app"] = app_pkg

from app.rag.confidence import assess_confidence
from app.rag.eval_utils import EvalCase, evaluate_retrieval
from app.rag.query_intent import classify_query_intent
from app.rag.reference_parser import parse_exact_references


class ConfidenceEvalTests(unittest.TestCase):
    def test_exact_reference_no_match_returns_no_answer(self) -> None:
        query = "3.4 band talablarini ayt"
        ref = parse_exact_references(query)
        intent = classify_query_intent(query, ref)
        items = [
            {"score": 0.31, "semantic_score": 0.28, "keyword_score": 0.22, "clause_number": "5.2", "shnq_code": "SHNQ 2.01.05-24"},
        ]
        result = assess_confidence(
            items=items,
            strict_min_score=0.24,
            min_score=0.15,
            intent=intent,
            reference=ref,
        )
        self.assertTrue(result.no_answer)
        self.assertEqual(result.reason, "exact_clause_not_found")

    def test_eval_utils_hit_rate_and_mrr(self) -> None:
        cases = [
            EvalCase(question="Q1", expected_doc_codes=["SHNQ 2.01.05-24"]),
            EvalCase(question="Q2", expected_table_numbers=["5"]),
        ]

        def fake_retrieve(question: str) -> list[dict[str, object]]:
            if question == "Q1":
                return [{"shnq_code": "SHNQ 2.01.05-24", "clause_number": "3.4", "table_number": ""}]
            return [{"shnq_code": "SHNQ 2.07.01-23", "clause_number": "", "table_number": "5"}]

        summary = evaluate_retrieval(cases, fake_retrieve, k=3)
        self.assertEqual(summary.total, 2)
        self.assertGreaterEqual(summary.hit_rate_at_k, 1.0)
        self.assertGreaterEqual(summary.mrr, 1.0)


if __name__ == "__main__":
    unittest.main()
