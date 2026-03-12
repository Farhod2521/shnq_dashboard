import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "app" not in sys.modules:
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = [str(ROOT / "app")]
    sys.modules["app"] = app_pkg

from app.rag.confidence import assess_confidence
from app.rag.numeric_reasoner import parse_numeric_query, score_numeric_text
from app.rag.query_expansion import expand_clause_discovery_queries
from app.rag.query_intent import classify_query_intent
from app.rag.reference_parser import parse_exact_references
from app.rag.re_ranker import rerank_clauses


@dataclass
class DummyClause:
    clause_id: str
    shnq_code: str
    title: str
    snippet: str
    clause_number: str | None = None
    dense_score: float = 0.0
    lexical_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)


class NumericClauseDiscoveryTests(unittest.TestCase):
    def test_exact_shnq_and_band_query(self) -> None:
        query = "SHNQ 2.05.07-24 147-band Evakuatsiya yo'laklarining minimal kengligi qancha bo'lishi kerak?"
        ref = parse_exact_references(query)
        intent = classify_query_intent(query, ref)
        self.assertIn("SHNQ 2.05.07-24", ref.document_codes)
        self.assertIn("147", ref.clause_numbers)
        self.assertEqual(intent.intent, "exact_band_reference")

        ranked = rerank_clauses(
            query=query,
            items=[
                DummyClause(
                    clause_id="c147",
                    shnq_code="SHNQ 2.05.07-24",
                    title="Band 147",
                    snippet="147-band: o'tish yo'lining kengligi kamida 0,8 m bo'lishi kerak.",
                    clause_number="147",
                    dense_score=0.31,
                    lexical_score=0.42,
                    hybrid_score=0.39,
                ),
                DummyClause(
                    clause_id="c150",
                    shnq_code="SHNQ 2.05.07-24",
                    title="Band 150",
                    snippet="150-band: evakuatsiya yo'lagi kengligi 1 m qabul qilinadi.",
                    clause_number="150",
                    dense_score=0.33,
                    lexical_score=0.38,
                    hybrid_score=0.4,
                ),
            ],
            limit=2,
        )
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].clause_number, "147")
        self.assertIn("0,8 m", ranked[0].snippet)

    def test_shnq_without_band_uses_numeric_minimum_signal(self) -> None:
        query = "SHNQ 2.05.07-24 Evakuatsiya yo'laklarining minimal kengligi qancha bo'lishi kerak?"
        ref = parse_exact_references(query)
        intent = classify_query_intent(query, ref)
        self.assertIn("SHNQ 2.05.07-24", ref.document_codes)
        self.assertNotIn("147", ref.clause_numbers)
        self.assertIn(intent.intent, {"topical_search", "general_synthesis"})

        ranked = rerank_clauses(
            query=query,
            items=[
                DummyClause(
                    clause_id="c147",
                    shnq_code="SHNQ 2.05.07-24",
                    title="Band 147",
                    snippet="147-band: evakuatsiya o'tish yo'lining kengligi kamida 0,8 m bo'lishi kerak.",
                    clause_number="147",
                    dense_score=0.23,
                    lexical_score=0.29,
                    hybrid_score=0.27,
                ),
                DummyClause(
                    clause_id="c151",
                    shnq_code="SHNQ 2.05.07-24",
                    title="Band 151",
                    snippet="151-band: ayrim hollarda yo'lak kengligi 1 m bo'lishi mumkin.",
                    clause_number="151",
                    dense_score=0.25,
                    lexical_score=0.31,
                    hybrid_score=0.3,
                ),
            ],
            limit=2,
        )
        self.assertEqual(ranked[0].clause_number, "147")

    def test_no_document_code_query_expansion_for_clause_discovery(self) -> None:
        query = "Evakuatsiya yo'laklarining minimal kengligi qancha bo'lishi kerak?"
        ref = parse_exact_references(query)
        profile = parse_numeric_query(query)
        expansions = expand_clause_discovery_queries(query, ref, profile)
        self.assertFalse(ref.document_codes)
        self.assertTrue(profile.is_numeric_query)
        self.assertGreaterEqual(len(expansions), 3)
        self.assertTrue(any("band" in item.lower() for item in expansions))

    def test_numeric_minimum_query_profile(self) -> None:
        query = "Evakuatsiya yo'lagi minimal kengligi kamida qancha bo'lishi kerak?"
        profile = parse_numeric_query(query)
        self.assertTrue(profile.is_numeric_query)
        self.assertEqual(profile.comparator, "min")
        self.assertIn("kenglik", profile.property_terms)

    def test_multiple_numeric_candidates_prefers_most_relevant_evidence(self) -> None:
        query = "Minimal kenglik qancha bo'lishi kerak?"
        profile = parse_numeric_query(query)
        match = score_numeric_text(
            profile,
            "Band 147: kenglik kamida 0,8 m bo'lishi kerak. Band 151: ayrim yo'laklarda 1 m tavsiya etiladi.",
        )
        self.assertGreater(match.score, 0.2)
        self.assertIsNotNone(match.best)
        self.assertIn("0,8", (match.best.raw if match.best else ""))

    def test_false_no_answer_regression_with_numeric_signal(self) -> None:
        query = "Minimal kenglik qancha?"
        ref = parse_exact_references(query)
        intent = classify_query_intent(query, ref)
        result = assess_confidence(
            items=[{"score": 0.12, "semantic_score": 0.11, "keyword_score": 0.1, "shnq_code": "SHNQ 2.05.07-24"}],
            strict_min_score=0.24,
            min_score=0.15,
            intent=intent,
            reference=ref,
            numeric_signal=0.42,
        )
        self.assertFalse(result.no_answer)

    def test_clause_discovery_regression_without_document_code(self) -> None:
        query = "Evakuatsiya yo'laklarining minimal kengligi qancha bo'lishi kerak?"
        ranked = rerank_clauses(
            query=query,
            items=[
                DummyClause(
                    clause_id="generic-1m",
                    shnq_code="SHNQ X",
                    title="Band 21",
                    snippet="Band 21: yo'lak kengligi 1 m bo'lishi mumkin.",
                    clause_number="21",
                    dense_score=0.34,
                    lexical_score=0.3,
                    hybrid_score=0.35,
                ),
                DummyClause(
                    clause_id="specific-08m",
                    shnq_code="SHNQ 2.05.07-24",
                    title="Band 147",
                    snippet="Band 147: evakuatsiya o'tish yo'lining kengligi kamida 0,8 m bo'lishi kerak.",
                    clause_number="147",
                    dense_score=0.28,
                    lexical_score=0.26,
                    hybrid_score=0.27,
                ),
            ],
            limit=2,
        )
        self.assertEqual(ranked[0].clause_number, "147")


if __name__ == "__main__":
    unittest.main()
