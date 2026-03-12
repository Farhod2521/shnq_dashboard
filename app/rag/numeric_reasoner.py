from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ComparatorType = Literal["min", "max", "exact", "unknown"]

_WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")
_VALUE_UNIT_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>mm|sm|cm|m|metr(?:i|a|)?|meter|metre|foiz|%)\b",
    re.IGNORECASE,
)
_MIN_TERMS = (
    "minimal",
    "eng kam",
    "kamida",
    "kam bo'lmasligi",
    "at least",
)
_MAX_TERMS = (
    "maksimal",
    "eng ko'p",
    "ko'pi bilan",
    "ortiq bo'lmasligi",
    "at most",
)
_EXACT_TERMS = (
    "aniq",
    "teng",
    "exact",
)
_NUMERIC_QUESTION_TERMS = ("qancha", "necha", "qanday", "qiymat", "talab", "bo'lishi kerak")
_PROPERTY_TERMS = (
    "kenglik",
    "balandlik",
    "masofa",
    "uzunlik",
    "qalinlik",
    "foiz",
    "diametr",
    "radius",
    "yuzasi",
    "hajm",
)
_PROPERTY_ALIASES: dict[str, tuple[str, ...]] = {
    "kenglik": ("kenglik", "kengligi", "kenglig"),
    "balandlik": ("balandlik", "balandligi", "balandlig"),
    "masofa": ("masofa", "masofasi", "masof"),
    "uzunlik": ("uzunlik", "uzunligi", "uzunlig"),
    "qalinlik": ("qalinlik", "qalinligi", "qalinlig"),
    "foiz": ("foiz", "foizi"),
    "diametr": ("diametr", "diametri"),
    "radius": ("radius", "radiusi"),
    "yuzasi": ("yuzasi", "yuzas"),
    "hajm": ("hajm", "hajmi"),
}
_MIN_HINT_TERMS = ("kamida", "minimal", "eng kam")
_MAX_HINT_TERMS = ("maksimal", "ko'pi bilan", "eng ko'p")


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().replace("\u2019", "'").replace("`", "'").split())


def _normalize_unit(raw_unit: str) -> str:
    unit = _normalize(raw_unit)
    if unit == "mm":
        return "mm"
    if unit in {"cm", "sm"}:
        return "cm"
    if unit in {"m", "metr", "metri", "metra", "meter", "metre"}:
        return "m"
    if unit in {"foiz", "%"}:
        return "%"
    return unit


def _normalize_value(value: float, unit: str) -> float | None:
    if unit == "mm":
        return value / 1000.0
    if unit == "cm":
        return value / 100.0
    if unit == "m":
        return value
    return None


@dataclass(slots=True)
class NumericQueryProfile:
    is_numeric_query: bool
    comparator: ComparatorType
    property_terms: list[str]
    unit_hints: list[str]
    query_values: list[float]
    query_units: list[str]


@dataclass(slots=True)
class NumericEvidence:
    raw: str
    value: float
    unit: str
    normalized_value: float | None
    span_start: int
    span_end: int


@dataclass(slots=True)
class NumericMatch:
    score: float
    best: NumericEvidence | None
    evidence_count: int


def parse_numeric_query(query: str) -> NumericQueryProfile:
    text = _normalize(query)
    comparator: ComparatorType = "unknown"
    if any(term in text for term in _MIN_TERMS):
        comparator = "min"
    elif any(term in text for term in _MAX_TERMS):
        comparator = "max"
    elif any(term in text for term in _EXACT_TERMS):
        comparator = "exact"

    property_terms = [
        term
        for term in _PROPERTY_TERMS
        if any(alias in text for alias in _PROPERTY_ALIASES.get(term, (term,)))
    ]
    evidences = extract_numeric_evidences(query)
    unit_hints = list(dict.fromkeys([e.unit for e in evidences]))
    query_values = [e.value for e in evidences]
    query_units = [e.unit for e in evidences]

    has_question_numeric_signal = any(term in text for term in _NUMERIC_QUESTION_TERMS)
    is_numeric_query = bool(
        comparator != "unknown"
        or evidences
        or (property_terms and has_question_numeric_signal)
    )
    return NumericQueryProfile(
        is_numeric_query=is_numeric_query,
        comparator=comparator,
        property_terms=property_terms,
        unit_hints=unit_hints,
        query_values=query_values,
        query_units=query_units,
    )


def extract_numeric_evidences(text: str) -> list[NumericEvidence]:
    normalized = _normalize(text)
    out: list[NumericEvidence] = []
    for match in _VALUE_UNIT_RE.finditer(normalized):
        raw_value = (match.group("value") or "").replace(",", ".").strip()
        raw_unit = (match.group("unit") or "").strip()
        try:
            value = float(raw_value)
        except ValueError:
            continue
        unit = _normalize_unit(raw_unit)
        out.append(
            NumericEvidence(
                raw=match.group(0),
                value=value,
                unit=unit,
                normalized_value=_normalize_value(value, unit),
                span_start=match.start(),
                span_end=match.end(),
            )
        )
    return out


def format_numeric_evidence(evidence: NumericEvidence | None) -> str | None:
    if not evidence:
        return None
    value_str = f"{evidence.value:.3f}".rstrip("0").rstrip(".").replace(".", ",")
    if evidence.unit == "%":
        return f"{value_str}%"
    return f"{value_str} {evidence.unit}"


def _comparator_score(profile: NumericQueryProfile, text: str) -> float:
    normalized = _normalize(text)
    if profile.comparator == "min":
        if any(term in normalized for term in _MIN_HINT_TERMS):
            return 0.22
        if any(term in normalized for term in _MAX_HINT_TERMS):
            return -0.08
        return 0.06
    if profile.comparator == "max":
        if any(term in normalized for term in _MAX_HINT_TERMS):
            return 0.22
        if any(term in normalized for term in _MIN_HINT_TERMS):
            return -0.08
        return 0.06
    if profile.comparator == "exact":
        return 0.12 if "aniq" in normalized else 0.04
    return 0.04


def _query_value_alignment(profile: NumericQueryProfile, evidence: NumericEvidence) -> float:
    if not profile.query_values or not profile.query_units:
        return 0.0
    aligned_values: list[float] = []
    for value, unit in zip(profile.query_values, profile.query_units):
        norm_unit = _normalize_unit(unit)
        norm_value = _normalize_value(value, norm_unit)
        if norm_value is None or evidence.normalized_value is None:
            continue
        aligned_values.append(abs(evidence.normalized_value - norm_value))
    if not aligned_values:
        return 0.0
    best_gap = min(aligned_values)
    if best_gap <= 0.001:
        return 0.18
    if best_gap <= 0.02:
        return 0.1
    return -0.04


def score_numeric_text(profile: NumericQueryProfile, text: str) -> NumericMatch:
    if not profile.is_numeric_query:
        return NumericMatch(score=0.0, best=None, evidence_count=0)

    normalized = _normalize(text)
    evidences = extract_numeric_evidences(normalized)
    if not evidences:
        return NumericMatch(score=0.0, best=None, evidence_count=0)

    property_bonus = 0.18 if any(term in normalized for term in profile.property_terms) else 0.04
    comparator_bonus = _comparator_score(profile, normalized)
    has_normative_phrase = 0.08 if ("bo'lishi kerak" in normalized or "kerak" in normalized) else 0.0

    best_score = -1.0
    best_evidence: NumericEvidence | None = None
    unit_hints = set(profile.unit_hints)
    for evidence in evidences:
        unit_score = 0.12 if not unit_hints else (0.2 if evidence.unit in unit_hints else 0.03)
        value_alignment = _query_value_alignment(profile, evidence)
        score = 0.12 + unit_score + property_bonus + comparator_bonus + has_normative_phrase + value_alignment
        if score > best_score:
            best_score = score
            best_evidence = evidence

    clamped = max(0.0, min(1.0, best_score))
    return NumericMatch(score=clamped, best=best_evidence, evidence_count=len(evidences))


def extract_query_terms_for_numeric(query: str) -> list[str]:
    normalized = _normalize(query)
    terms = [token.lower() for token in _WORD_RE.findall(normalized) if len(token) > 2]
    uniq: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        uniq.append(term)
    return uniq[:12]
