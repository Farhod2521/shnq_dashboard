from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Callable


@dataclass(slots=True)
class EvalCase:
    question: str
    expected_doc_codes: list[str] = field(default_factory=list)
    expected_clause_numbers: list[str] = field(default_factory=list)
    expected_table_numbers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalResult:
    question: str
    hit_at_k: bool
    reciprocal_rank: float
    doc_hit: bool
    clause_hit: bool
    table_hit: bool


@dataclass(slots=True)
class EvalSummary:
    total: int
    hit_rate_at_k: float
    mrr: float
    doc_hit_rate: float
    clause_hit_rate: float
    table_hit_rate: float
    details: list[EvalResult]


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def evaluate_retrieval(
    cases: list[EvalCase],
    retrieve_fn: Callable[[str], list[dict[str, object]]],
    k: int = 5,
) -> EvalSummary:
    details: list[EvalResult] = []
    for case in cases:
        rows = retrieve_fn(case.question)[: max(1, k)]
        expected_docs = {_norm(v) for v in case.expected_doc_codes if _norm(v)}
        expected_clauses = {_norm(v) for v in case.expected_clause_numbers if _norm(v)}
        expected_tables = {_norm(v) for v in case.expected_table_numbers if _norm(v)}

        hit = False
        rr = 0.0
        doc_hit = False
        clause_hit = False
        table_hit = False
        for rank, row in enumerate(rows, start=1):
            code = _norm(str(row.get("shnq_code") or ""))
            clause = _norm(str(row.get("clause_number") or ""))
            table = _norm(str(row.get("table_number") or ""))
            row_match = False
            if expected_docs and code in expected_docs:
                doc_hit = True
                row_match = True
            if expected_clauses and clause in expected_clauses:
                clause_hit = True
                row_match = True
            if expected_tables and table in expected_tables:
                table_hit = True
                row_match = True
            if row_match and not hit:
                hit = True
                rr = 1.0 / rank

        details.append(
            EvalResult(
                question=case.question,
                hit_at_k=hit,
                reciprocal_rank=rr,
                doc_hit=doc_hit,
                clause_hit=clause_hit,
                table_hit=table_hit,
            )
        )

    total = len(details)
    if total == 0:
        return EvalSummary(
            total=0,
            hit_rate_at_k=0.0,
            mrr=0.0,
            doc_hit_rate=0.0,
            clause_hit_rate=0.0,
            table_hit_rate=0.0,
            details=[],
        )
    return EvalSummary(
        total=total,
        hit_rate_at_k=mean(1.0 if d.hit_at_k else 0.0 for d in details),
        mrr=mean(d.reciprocal_rank for d in details),
        doc_hit_rate=mean(1.0 if d.doc_hit else 0.0 for d in details),
        clause_hit_rate=mean(1.0 if d.clause_hit else 0.0 for d in details),
        table_hit_rate=mean(1.0 if d.table_hit else 0.0 for d in details),
        details=details,
    )

