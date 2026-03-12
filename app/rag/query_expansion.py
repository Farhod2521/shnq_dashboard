from __future__ import annotations

import re

from app.rag.numeric_reasoner import NumericQueryProfile
from app.rag.reference_parser import ExactReference


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().replace("\u2019", "'").replace("`", "'").split())


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join((value or "").split()).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _strip_explicit_references(query: str) -> str:
    text = _normalize(query)
    text = re.sub(r"\b(shnq|qmq|kmk|snip)\s*[0-9][0-9.\-]*\b", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(?:band|modda)\s*[-.:]?\s*\d+(?:\.\d+){0,3}\b|\b\d+(?:\.\d+){0,3}\s*[-.:]?\s*(?:band|modda)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return " ".join(text.split()).strip()


def expand_clause_discovery_queries(
    query: str,
    reference: ExactReference,
    numeric_profile: NumericQueryProfile | None = None,
) -> list[str]:
    base = " ".join((query or "").split()).strip()
    if not base:
        return []

    expansions: list[str] = [base]
    stripped = _strip_explicit_references(base)
    if stripped and stripped != _normalize(base):
        expansions.append(stripped)

    if reference.document_codes and reference.clause_numbers:
        expansions.append(f"{base} band matni")
    elif reference.document_codes:
        expansions.append(f"{base} band talabi")
        expansions.append(f"{base} me'yor talabi")
    else:
        expansions.append(f"{base} shnq band talabi")
        expansions.append(f"{base} normativ band")

    profile = numeric_profile
    if profile and profile.is_numeric_query:
        if profile.comparator == "min":
            expansions.append(f"{base} kamida me'yor")
            expansions.append(f"{base} minimal talab band")
        elif profile.comparator == "max":
            expansions.append(f"{base} ko'pi bilan me'yor")
            expansions.append(f"{base} maksimal talab band")
        else:
            expansions.append(f"{base} sonli norma")
        if profile.property_terms:
            term_block = " ".join(profile.property_terms[:2])
            expansions.append(f"{base} {term_block} normasi")

    return _dedupe(expansions)[:6]
