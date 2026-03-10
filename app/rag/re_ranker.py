from __future__ import annotations

import math
import re

from app.rag.retriever import RetrievedClause


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "") if len(w) > 2]


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

    for item in items:
        snippet_l = (item.snippet or "").lower()
        overlap = sum(1 for t in query_terms if t in snippet_l)
        coverage = overlap / max(len(query_terms), 1)

        # Hybrid relevance + lexical coverage + dense confidence.
        # This keeps speed high and improves precision on legal text.
        item.rerank_score = (
            (item.hybrid_score * 0.55)
            + (item.dense_score * 0.25)
            + (item.lexical_score * 0.10)
            + (coverage * 0.10)
        )
        if overlap > 0:
            item.rerank_score += min(0.03, math.log1p(overlap) * 0.01)
        item.signals["overlap"] = float(overlap)
        item.signals["coverage"] = float(coverage)

    items.sort(key=lambda x: x.rerank_score, reverse=True)
    return items[:limit]
