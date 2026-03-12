from __future__ import annotations

import re


# Legacy mojibake fragments produced when UTF-8 text is decoded as CP1251.
_CLASSIC_MOJIBAKE_RE = re.compile(
    "(?:\u0420\u0459|\u0420\u0406\u0420|\u0420\u00A0\u0432\u0402|\u0420\u0457\u0412|\u0413[\u0450\u0451])"
)
# Common broken Uzbek apostrophe sequences: oК», gКј, etc.
_APOSTROPHE_MOJIBAKE_RE = re.compile("\u041A[\u00BB\u0458\u0457\u00B0\u00B1\u0401\u0451]")


def _marker_count(text: str) -> int:
    return len(_CLASSIC_MOJIBAKE_RE.findall(text)) + len(_APOSTROPHE_MOJIBAKE_RE.findall(text))


def repair_mojibake(text: str | None) -> str:
    """Best-effort fix for UTF-8 text decoded as Windows-1251."""
    value = (text or "").replace("\ufeff", "")
    if not value:
        return ""
    if not (_CLASSIC_MOJIBAKE_RE.search(value) or _APOSTROPHE_MOJIBAKE_RE.search(value)):
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
