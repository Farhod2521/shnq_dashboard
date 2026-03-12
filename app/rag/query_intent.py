from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.rag.numeric_reasoner import parse_numeric_query
from app.rag.reference_parser import ExactReference, parse_exact_references


IntentType = Literal[
    "exact_band_reference",
    "topical_search",
    "table_lookup",
    "image_lookup",
    "compare_documents",
    "general_synthesis",
]

_COMPARE_TERMS = ("taqqos", "solishtir", "farq", "difference", "compare")
_TABLE_TERMS = ("jadval", "table", "satr", "ustun", "ilova", "appendix")
_IMAGE_TERMS = ("rasm", "image", "diagramma", "sxema", "surat", "chizma")
_BAND_TERMS = ("band", "modda", "bob")


def _normalize(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


@dataclass(slots=True)
class IntentResult:
    intent: IntentType
    confidence: float
    reason: str
    reference: ExactReference
    numeric_query: bool = False

    def to_debug_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "reference": self.reference.to_debug_dict(),
            "numeric_query": self.numeric_query,
        }


def classify_query_intent(query: str, reference: ExactReference | None = None) -> IntentResult:
    text = _normalize(query)
    ref = reference or parse_exact_references(text)
    numeric_profile = parse_numeric_query(text)
    has_table_word = any(term in text for term in _TABLE_TERMS)
    has_image_word = any(term in text for term in _IMAGE_TERMS)
    has_compare_word = any(term in text for term in _COMPARE_TERMS)
    has_band_word = any(term in text for term in _BAND_TERMS)

    if has_compare_word and (len(ref.document_codes) >= 2 or " va " in text or " bilan " in text):
        return IntentResult(
            intent="compare_documents",
            confidence=0.9,
            reason="compare_terms_detected",
            reference=ref,
            numeric_query=numeric_profile.is_numeric_query,
        )

    if ref.table_numbers or ref.appendix_numbers or has_table_word:
        return IntentResult(
            intent="table_lookup",
            confidence=0.88 if (ref.table_numbers or ref.appendix_numbers) else 0.72,
            reason="table_reference_or_terms",
            reference=ref,
            numeric_query=numeric_profile.is_numeric_query,
        )

    if has_image_word:
        return IntentResult(
            intent="image_lookup",
            confidence=0.82,
            reason="image_terms_detected",
            reference=ref,
            numeric_query=numeric_profile.is_numeric_query,
        )

    if ref.clause_numbers and (has_band_word or ref.has_explicit_reference):
        return IntentResult(
            intent="exact_band_reference",
            confidence=0.9,
            reason="clause_reference_detected",
            reference=ref,
            numeric_query=numeric_profile.is_numeric_query,
        )

    token_count = len(text.split())
    if token_count >= 4 and not ref.has_explicit_reference:
        return IntentResult(
            intent="topical_search",
            confidence=0.76 if numeric_profile.is_numeric_query else 0.7,
            reason="numeric_norm_query" if numeric_profile.is_numeric_query else "descriptive_query_without_exact_reference",
            reference=ref,
            numeric_query=numeric_profile.is_numeric_query,
        )

    return IntentResult(
        intent="general_synthesis",
        confidence=0.6,
        reason="default_fallback",
        reference=ref,
        numeric_query=numeric_profile.is_numeric_query,
    )
