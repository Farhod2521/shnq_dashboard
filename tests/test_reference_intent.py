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


class ReferenceIntentTests(unittest.TestCase):
    def test_parse_exact_reference_with_table_and_clause(self) -> None:
        text = "SHNQ 2.01.05-24 bo'yicha 3.4 band va 5-jadval talablarini ayting"
        ref = parse_exact_references(text)
        self.assertIn("SHNQ 2.01.05-24", ref.document_codes)
        self.assertIn("3.4", ref.clause_numbers)
        self.assertIn("5", ref.table_numbers)
        self.assertTrue(ref.has_explicit_reference)

    def test_intent_compare_documents(self) -> None:
        text = "SHNQ 2.01.05-24 va SHNQ 2.07.01-23 ni taqqosla"
        ref = parse_exact_references(text)
        intent = classify_query_intent(text, ref)
        self.assertEqual(intent.intent, "compare_documents")
        self.assertGreaterEqual(intent.confidence, 0.8)

    def test_intent_table_lookup(self) -> None:
        text = "9-jadvalda deraza bo'yicha talablar"
        intent = classify_query_intent(text, parse_exact_references(text))
        self.assertEqual(intent.intent, "table_lookup")

    def test_numeric_query_flag(self) -> None:
        text = "Evakuatsiya yo'lagi minimal kengligi qancha bo'lishi kerak?"
        intent = classify_query_intent(text, parse_exact_references(text))
        self.assertTrue(intent.numeric_query)


if __name__ == "__main__":
    unittest.main()
