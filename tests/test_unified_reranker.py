import unittest
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "app" not in sys.modules:
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(ROOT / "app")]
    sys.modules["app"] = app_pkg

from app.rag.query_intent import classify_query_intent
from app.rag.reference_parser import parse_exact_references
from app.rag.unified_reranker import rerank_mixed_items


class UnifiedRerankerTests(unittest.TestCase):
    def test_rerank_prioritizes_exact_clause_and_dedupes(self) -> None:
        query = "SHNQ bo'yicha 3.4 band nima deydi"
        ref = parse_exact_references(query)
        intent = classify_query_intent(query, ref)
        items = [
            {
                "kind": "clause",
                "score": 0.42,
                "snippet": "3.4 band: deraza uchun minimal ko'rsatkich ...",
                "shnq_code": "SHNQ 2.01.05-24",
                "clause_number": "3.4",
                "clause_id": "c1",
                "semantic_score": 0.33,
                "keyword_score": 0.4,
            },
            {
                "kind": "clause",
                "score": 0.41,
                "snippet": "3.4 band: deraza uchun minimal ko'rsatkich ...",
                "shnq_code": "SHNQ 2.01.05-24",
                "clause_number": "3.4",
                "clause_id": "c2",
                "semantic_score": 0.31,
                "keyword_score": 0.39,
            },
            {
                "kind": "clause",
                "score": 0.5,
                "snippet": "5.1 band: boshqa mavzu ...",
                "shnq_code": "SHNQ 2.01.05-24",
                "clause_number": "5.1",
                "clause_id": "c3",
                "semantic_score": 0.2,
                "keyword_score": 0.1,
            },
        ]
        out, debug = rerank_mixed_items(query=query, items=items, intent=intent, reference=ref, limit=5)
        self.assertGreaterEqual(debug.removed_duplicates, 1)
        self.assertTrue(out)
        self.assertEqual(out[0].get("clause_number"), "3.4")


if __name__ == "__main__":
    unittest.main()
