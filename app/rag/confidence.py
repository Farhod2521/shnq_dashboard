from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rag.query_intent import IntentResult
from app.rag.reference_parser import ExactReference


def _value(item: Any, key: str) -> float:
    if isinstance(item, dict):
        return float(item.get(key, 0.0) or 0.0)
    return float(getattr(item, key, 0.0) or 0.0)


def _text(item: Any, key: str) -> str:
    if isinstance(item, dict):
        return str(item.get(key, "") or "")
    return str(getattr(item, key, "") or "")


@dataclass(slots=True)
class ConfidenceResult:
    score: float
    label: str
    no_answer: bool
    reason: str
    conflicting_evidence: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "label": self.label,
            "no_answer": self.no_answer,
            "reason": self.reason,
            "conflicting_evidence": self.conflicting_evidence,
            "warning": self.warning,
        }


def assess_confidence(
    items: list[Any],
    strict_min_score: float,
    min_score: float,
    intent: IntentResult,
    reference: ExactReference,
    numeric_signal: float = 0.0,
) -> ConfidenceResult:
    if not items:
        return ConfidenceResult(
            score=0.0,
            label="low",
            no_answer=True,
            reason="no_retrieval_items",
            conflicting_evidence=False,
            warning=None,
        )
    top = items[0]
    top_score = _value(top, "score")
    top_sem = _value(top, "semantic_score")
    top_kw = _value(top, "keyword_score")
    signal = max(top_score, top_sem, top_kw, float(numeric_signal or 0.0))
    top_doc = _text(top, "shnq_code").lower()

    conflicting = False
    warning = None
    if len(items) > 1:
        second = items[1]
        second_score = _value(second, "score")
        second_doc = _text(second, "shnq_code").lower()
        close = abs(top_score - second_score) <= 0.03
        conflicting = bool(second_doc and top_doc and second_doc != top_doc and close and second_score >= min_score)
        if conflicting:
            warning = "Top results point to multiple documents with close evidence."

    # Exact reference queries should fail safely if no exact match exists.
    if intent.intent == "exact_band_reference" and reference.clause_numbers:
        target = {value.strip().lower() for value in reference.clause_numbers}
        has_exact = any(_text(item, "clause_number").strip().lower() in target for item in items[:5])
        if not has_exact:
            return ConfidenceResult(
                score=signal,
                label="low",
                no_answer=True,
                reason="exact_clause_not_found",
                conflicting_evidence=conflicting,
                warning=warning,
            )

    if signal >= strict_min_score:
        return ConfidenceResult(
            score=signal,
            label="high",
            no_answer=False,
            reason="signal_above_strict_threshold",
            conflicting_evidence=conflicting,
            warning=warning,
        )
    if signal >= min_score:
        return ConfidenceResult(
            score=signal,
            label="medium",
            no_answer=False,
            reason="signal_above_min_threshold",
            conflicting_evidence=conflicting,
            warning=warning,
        )
    return ConfidenceResult(
        score=signal,
        label="low",
        no_answer=True,
        reason="signal_below_min_threshold",
        conflicting_evidence=conflicting,
        warning=warning,
    )
