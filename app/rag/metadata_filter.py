from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass(slots=True)
class MetadataFilters:
    document_codes: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    section_ids: list[str] = field(default_factory=list)
    section_titles: list[str] = field(default_factory=list)
    clause_numbers: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    table_ids: list[str] = field(default_factory=list)
    image_ids: list[str] = field(default_factory=list)
    table_numbers: list[str] = field(default_factory=list)
    appendix_numbers: list[str] = field(default_factory=list)

    def normalized(self) -> "MetadataFilters":
        return MetadataFilters(
            document_codes=_dedupe(self.document_codes),
            document_ids=_dedupe(self.document_ids),
            section_ids=_dedupe(self.section_ids),
            section_titles=_dedupe(self.section_titles),
            clause_numbers=_dedupe(self.clause_numbers),
            pages=_dedupe(self.pages),
            languages=_dedupe(self.languages),
            content_types=_dedupe(self.content_types),
            table_ids=_dedupe(self.table_ids),
            image_ids=_dedupe(self.image_ids),
            table_numbers=_dedupe(self.table_numbers),
            appendix_numbers=_dedupe(self.appendix_numbers),
        )

    def has_any(self) -> bool:
        return any(
            [
                self.document_codes,
                self.document_ids,
                self.section_ids,
                self.section_titles,
                self.clause_numbers,
                self.pages,
                self.languages,
                self.content_types,
                self.table_ids,
                self.image_ids,
                self.table_numbers,
                self.appendix_numbers,
            ]
        )


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


def _pick_attr(item: Any, name: str) -> str:
    value = ""
    if isinstance(item, dict):
        value = str(item.get(name) or "")
    else:
        value = str(getattr(item, name, "") or "")
    return value.strip()


def _any_match(value: str, expected: list[str], contains: bool = False) -> bool:
    if not expected:
        return True
    source = _norm(value)
    if not source:
        return False
    if contains:
        return any(_norm(item) in source for item in expected if _norm(item))
    return any(source == _norm(item) for item in expected if _norm(item))


def match_item_filters(item: Any, filters: MetadataFilters | None) -> bool:
    if not filters:
        return True
    f = filters.normalized()
    if not f.has_any():
        return True
    checks = [
        _any_match(_pick_attr(item, "shnq_code"), f.document_codes),
        _any_match(_pick_attr(item, "document_id"), f.document_ids),
        _any_match(_pick_attr(item, "section_id"), f.section_ids),
        _any_match(_pick_attr(item, "chapter"), f.section_titles, contains=True),
        _any_match(_pick_attr(item, "section_title"), f.section_titles, contains=True),
        _any_match(_pick_attr(item, "clause_number"), f.clause_numbers),
        _any_match(_pick_attr(item, "page"), f.pages),
        _any_match(_pick_attr(item, "language"), f.languages),
        _any_match(_pick_attr(item, "content_type"), f.content_types),
        _any_match(_pick_attr(item, "table_id"), f.table_ids),
        _any_match(_pick_attr(item, "image_id"), f.image_ids),
        _any_match(_pick_attr(item, "table_number"), f.table_numbers),
        _any_match(_pick_attr(item, "appendix_number"), f.appendix_numbers),
    ]
    return all(checks)


def apply_metadata_filters(items: list[Any], filters: MetadataFilters | None) -> list[Any]:
    if not filters:
        return items
    return [item for item in items if match_item_filters(item, filters)]
