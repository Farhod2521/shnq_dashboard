from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.rag.numeric_reasoner import parse_numeric_query, score_numeric_text
from app.rag.query_intent import IntentResult
from app.rag.reference_parser import ExactReference


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")
APOSTROPHE_VARIANTS = str.maketrans({
    "`": "'",
    "\u2019": "'",
    "\u2018": "'",
    "\u02bc": "'",
    "\u02bb": "'",
    "\u2032": "'",
})


def _tokenize(text: str) -> set[str]:
    normalized = (text or "").lower().translate(APOSTROPHE_VARIANTS)
    return {_stem_token(w) for w in WORD_RE.findall(normalized) if len(w) > 2}


def _stem_token(token: str) -> str:
    value = (token or "").strip().lower().translate(APOSTROPHE_VARIANTS)
    suffixes = (
        "larining",
        "laridan",
        "larida",
        "lariga",
        "larini",
        "larning",
        "lardan",
        "sigacha",
        "igacha",
        "sidan",
        "idan",
        "gacha",
        "lari",
        "ning",
        "dagi",
        "dan",
        "lar",
        "gan",
        "si",
        "ga",
        "da",
        "ni",
        "i",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if value.endswith(suffix) and len(value) - len(suffix) >= 4:
                value = value[: -len(suffix)]
                changed = True
                break
    return value


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _fingerprint(text: str) -> str:
    tokens = sorted(_tokenize(text))
    return " ".join(tokens[:40])


def _item_attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _set_item_score(item: Any, score: float) -> None:
    if isinstance(item, dict):
        item["score"] = score
        return
    setattr(item, "score", score)


@dataclass(slots=True)
class UnifiedRerankDebug:
    before_count: int
    after_count: int
    removed_duplicates: int


def rerank_mixed_items(
    query: str,
    items: list[Any],
    intent: IntentResult,
    reference: ExactReference,
    limit: int,
    duplicate_sim_threshold: float = 0.9,
) -> tuple[list[Any], UnifiedRerankDebug]:
    if not items:
        return [], UnifiedRerankDebug(before_count=0, after_count=0, removed_duplicates=0)

    query_terms = _tokenize(query)
    numeric_profile = parse_numeric_query(query)
    reranked: list[Any] = []
    for item in items:
        base = float(_item_attr(item, "score", 0.0) or 0.0)
        snippet = str(_item_attr(item, "snippet", "") or "")
        kind = str(_item_attr(item, "kind", "") or "")
        overlap = sum(1 for term in query_terms if term in _norm(snippet))
        coverage = overlap / max(len(query_terms), 1)
        semantic = float(_item_attr(item, "semantic_score", 0.0) or 0.0)
        keyword = float(_item_attr(item, "keyword_score", 0.0) or 0.0)
        score = base + (coverage * 0.17) + (semantic * 0.06) + (keyword * 0.08)
        if numeric_profile.is_numeric_query and kind in {"clause", "table_row"}:
            numeric = score_numeric_text(numeric_profile, snippet)
            score += numeric.score * 0.2
            if numeric.score <= 0.01:
                score -= 0.03

        if intent.intent == "table_lookup" and kind == "table_row":
            score += 0.22
        if intent.intent == "image_lookup" and kind == "image":
            score += 0.25
        if intent.intent == "exact_band_reference" and kind == "clause":
            score += 0.2

        clause_number = _norm(str(_item_attr(item, "clause_number", "") or ""))
        table_number = _norm(str(_item_attr(item, "table_number", "") or ""))
        appendix_number = _norm(str(_item_attr(item, "appendix_number", "") or ""))
        if reference.clause_numbers and clause_number in {_norm(x) for x in reference.clause_numbers}:
            score += 0.35
        if reference.table_numbers and table_number in {_norm(x) for x in reference.table_numbers}:
            score += 0.4
        if reference.appendix_numbers and appendix_number in {_norm(x) for x in reference.appendix_numbers}:
            score += 0.22

        if overlap > 0:
            score += min(0.04, math.log1p(overlap) * 0.015)

        _set_item_score(item, float(score))
        reranked.append(item)

    reranked.sort(key=lambda x: float(_item_attr(x, "score", 0.0) or 0.0), reverse=True)

    out: list[Any] = []
    seen_id: set[str] = set()
    seen_fp: list[str] = []
    duplicates = 0
    for item in reranked:
        identity = ":".join(
            [
                str(_item_attr(item, "kind", "") or ""),
                str(_item_attr(item, "clause_id", "") or ""),
                str(_item_attr(item, "table_id", "") or ""),
                str(_item_attr(item, "image_id", "") or ""),
                str(_item_attr(item, "title", "") or ""),
            ]
        )
        if identity in seen_id:
            duplicates += 1
            continue
        snippet_fp = _fingerprint(str(_item_attr(item, "snippet", "") or ""))
        too_similar = False
        for fp in seen_fp:
            if not fp or not snippet_fp:
                continue
            shared = len(set(fp.split()) & set(snippet_fp.split()))
            denom = max(len(set(fp.split())), len(set(snippet_fp.split())), 1)
            sim = shared / denom
            if sim >= duplicate_sim_threshold:
                too_similar = True
                break
        if too_similar:
            duplicates += 1
            continue
        seen_id.add(identity)
        seen_fp.append(snippet_fp)
        out.append(item)
        if len(out) >= max(1, limit):
            break

    return out, UnifiedRerankDebug(
        before_count=len(items),
        after_count=len(out),
        removed_duplicates=duplicates,
    )
