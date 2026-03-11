from __future__ import annotations

import re


_MOJIBAKE_MARKERS = (
    "К»",
    "Кј",
    "вЂ",
    "Р‚",
    "п»ї",
    "Ð",
    "Ñ",
)

_SUSPECT_RE = re.compile(r"[КвРпÐÑ]")


def _marker_count(text: str) -> int:
    return sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)


def repair_mojibake(text: str | None) -> str:
    """Best-effort fix for UTF-8 text decoded as Windows-1251."""
    value = (text or "").replace("\ufeff", "")
    if not value:
        return ""
    if not _SUSPECT_RE.search(value):
        return value

    try:
        repaired = value.encode("windows-1251", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return value

    if not repaired:
        return value

    before = _marker_count(value)
    after = _marker_count(repaired)
    if after <= before and len(repaired) >= int(len(value) * 0.75):
        return repaired
    return value


def to_cp1251_mojibake(text: str | None) -> str:
    """Generate mojibake variant to match already-corrupted DB content."""
    value = (text or "").strip()
    if not value:
        return ""
    try:
        return value.encode("utf-8", errors="ignore").decode("windows-1251", errors="ignore")
    except Exception:
        return ""

