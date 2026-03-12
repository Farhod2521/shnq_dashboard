from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.rag.numeric_reasoner import parse_numeric_query, score_numeric_text

if TYPE_CHECKING:
    from app.rag.retriever import RetrievedClause
else:
    RetrievedClause = Any


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")
APOSTROPHE_VARIANTS = str.maketrans({
    "`": "'",
    "\u2019": "'",
    "\u2018": "'",
    "\u02bc": "'",
    "\u02bb": "'",
    "\u2032": "'",
})


def _tokenize(text: str) -> list[str]:
    normalized = (text or "").lower().translate(APOSTROPHE_VARIANTS)
    return [_stem_token(w) for w in WORD_RE.findall(normalized) if len(w) > 2]


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


def _fingerprint(text: str) -> str:
    tokens = sorted(set(_tokenize(text)))
    return " ".join(tokens[:40])


def _dedupe_items(items: list[RetrievedClause], sim_threshold: float = 0.9) -> list[RetrievedClause]:
    out: list[RetrievedClause] = []
    by_doc_fingerprint: defaultdict[str, list[str]] = defaultdict(list)
    for item in items:
        doc_key = (item.shnq_code or "").strip().lower()
        fp = _fingerprint(item.snippet)
        if not fp:
            out.append(item)
            continue
        duplicate = False
        for seen_fp in by_doc_fingerprint[doc_key]:
            shared = len(set(seen_fp.split()) & set(fp.split()))
            denom = max(len(set(seen_fp.split())), len(set(fp.split())), 1)
            similarity = shared / denom
            if similarity >= sim_threshold:
                duplicate = True
                break
        if duplicate:
            continue
        by_doc_fingerprint[doc_key].append(fp)
        out.append(item)
    return out


def rerank_clauses(
    query: str,
    items: list[RetrievedClause],
    limit: int,
) -> list[RetrievedClause]:
    if not items:
        return []

    query_terms = set(_tokenize(query))
    if not query_terms:
        for item in items:
            item.rerank_score = item.hybrid_score
        items.sort(key=lambda x: x.rerank_score, reverse=True)
        return items[:limit]

    numeric_profile = parse_numeric_query(query)

    for item in items:
        snippet_l = (item.snippet or "").lower()
        overlap = sum(1 for t in query_terms if t in snippet_l)
        coverage = overlap / max(len(query_terms), 1)
        exact_clause_boost = 0.0
        if item.clause_number and item.clause_number in query:
            exact_clause_boost = 0.12
        numeric_bonus = 0.0
        if numeric_profile.is_numeric_query:
            numeric_match = score_numeric_text(numeric_profile, item.snippet or "")
            numeric_bonus = numeric_match.score * 0.22
            if numeric_match.score <= 0.01:
                numeric_bonus -= 0.03

        item.rerank_score = (
            (item.hybrid_score * 0.52)
            + (item.dense_score * 0.24)
            + (item.lexical_score * 0.12)
            + (coverage * 0.12)
            + exact_clause_boost
            + numeric_bonus
        )
        if overlap > 0:
            item.rerank_score += min(0.03, math.log1p(overlap) * 0.01)
        item.signals["overlap"] = float(overlap)
        item.signals["coverage"] = float(coverage)
        item.signals["exact_clause_boost"] = float(exact_clause_boost)
        item.signals["numeric_bonus"] = float(max(0.0, numeric_bonus))

    items.sort(key=lambda x: x.rerank_score, reverse=True)
    deduped = _dedupe_items(items)
    return deduped[:limit]
