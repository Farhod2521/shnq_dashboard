from __future__ import annotations

import re
from dataclasses import dataclass, field


DOCUMENT_CODE_RE = re.compile(r"\b(shnq|qmq|kmk|snip)\s*([0-9][0-9.\-]*)\b", re.IGNORECASE)
CLAUSE_NUMBER_RE = re.compile(
    r"(?:\b(?:band|modda)(?:i|lar|da|ni|ga|dan|ning)?\s*[-.:]?\s*(\d+(?:\.\d+){0,3})\b|"
    r"\b(\d+(?:\.\d+){0,3})\s*[-.:]?\s*(?:band|modda)(?:i|lar|da|ni|ga|dan|ning)?\b)",
    re.IGNORECASE,
)
BARE_CLAUSE_NUMBER_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+){0,2})\b")
TABLE_NUMBER_RE = re.compile(
    r"(?:\bjadval(?:da|ni|ga|dan|ning|lar)?\s*[-.]?\s*(\d+(?:\.\d+)*[a-z]?)\b|"
    r"\b(\d+(?:\.\d+)*[a-z]?)\s*[-.]?\s*jadval(?:da|ni|ga|dan|ning|lar)?\b)",
    re.IGNORECASE,
)
APPENDIX_NUMBER_RE = re.compile(
    r"(?:\b(\d+)\s*[-.]?\s*ilova(?:si|da|ga|dan|ning|lar)?\b|"
    r"\bilova(?:si|da|ga|dan|ning|lar)?\s*[-.]?\s*(\d+)\b)",
    re.IGNORECASE,
)
CHAPTER_NUMBER_RE = re.compile(
    r"(?:\bbob\s*[-.:]?\s*(\d+(?:\.\d+)*)\b|\b(\d+(?:\.\d+)*)\s*[-.:]?\s*bob\b)",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _norm(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out


@dataclass(slots=True)
class ExactReference:
    document_codes: list[str] = field(default_factory=list)
    clause_numbers: list[str] = field(default_factory=list)
    chapter_numbers: list[str] = field(default_factory=list)
    table_numbers: list[str] = field(default_factory=list)
    appendix_numbers: list[str] = field(default_factory=list)
    has_explicit_reference: bool = False

    def to_debug_dict(self) -> dict[str, object]:
        return {
            "document_codes": self.document_codes,
            "clause_numbers": self.clause_numbers,
            "chapter_numbers": self.chapter_numbers,
            "table_numbers": self.table_numbers,
            "appendix_numbers": self.appendix_numbers,
            "has_explicit_reference": self.has_explicit_reference,
        }


def extract_document_codes(text: str) -> list[str]:
    query = _norm(text)
    out: list[str] = []
    for match in DOCUMENT_CODE_RE.finditer(query):
        out.append(f"{match.group(1).upper()} {match.group(2)}")
    return _dedupe(out)


def parse_exact_references(text: str) -> ExactReference:
    query = _norm(text)
    doc_codes = extract_document_codes(query)
    doc_number_parts: set[str] = set()
    for code in doc_codes:
        parts = code.split(maxsplit=1)
        if len(parts) == 2:
            doc_number_parts.add(parts[1].split("-")[0].strip())

    clause_numbers = [
        (match.group(1) or match.group(2) or "").strip()
        for match in CLAUSE_NUMBER_RE.finditer(query)
        if (match.group(1) or match.group(2))
    ]
    bare_clause_numbers = [
        match.group(1).strip()
        for match in BARE_CLAUSE_NUMBER_RE.finditer(query)
        if match.group(1) and match.group(1).strip() not in doc_number_parts
    ]
    table_numbers = [
        (match.group(1) or match.group(2) or "").strip()
        for match in TABLE_NUMBER_RE.finditer(query)
        if (match.group(1) or match.group(2))
    ]
    appendix_numbers = [
        (match.group(1) or match.group(2) or "").strip()
        for match in APPENDIX_NUMBER_RE.finditer(query)
        if (match.group(1) or match.group(2))
    ]
    chapter_numbers = [
        (match.group(1) or match.group(2) or "").strip()
        for match in CHAPTER_NUMBER_RE.finditer(query)
        if (match.group(1) or match.group(2))
    ]
    ref = ExactReference(
        document_codes=_dedupe(doc_codes),
        clause_numbers=_dedupe([*clause_numbers, *bare_clause_numbers]),
        chapter_numbers=_dedupe(chapter_numbers),
        table_numbers=_dedupe(table_numbers),
        appendix_numbers=_dedupe(appendix_numbers),
    )
    ref.has_explicit_reference = bool(
        ref.document_codes
        or ref.clause_numbers
        or ref.chapter_numbers
        or ref.table_numbers
        or ref.appendix_numbers
    )
    return ref
