from __future__ import annotations

from app.rag.retriever import RetrievedClause


def reciprocal_rank_fusion(
    dense_items: list[RetrievedClause],
    lexical_items: list[RetrievedClause],
    rrf_k: int = 60,
) -> list[RetrievedClause]:
    by_id: dict[str, RetrievedClause] = {}

    for rank, item in enumerate(dense_items, start=1):
        base = by_id.get(item.clause_id)
        if not base:
            base = item
            by_id[item.clause_id] = base
        base.hybrid_score += 1.0 / (rrf_k + rank)
        base.dense_score = max(base.dense_score, item.dense_score)
        base.signals["dense_rank"] = float(rank)

    for rank, item in enumerate(lexical_items, start=1):
        base = by_id.get(item.clause_id)
        if not base:
            base = item
            by_id[item.clause_id] = base
        else:
            if len(item.snippet) > len(base.snippet):
                base.snippet = item.snippet
            if item.title and item.title != "Band -":
                base.title = item.title
            if not base.shnq_code and item.shnq_code:
                base.shnq_code = item.shnq_code
        base.hybrid_score += 1.0 / (rrf_k + rank)
        base.lexical_score = max(base.lexical_score, item.lexical_score)
        base.signals["lexical_rank"] = float(rank)

    merged = list(by_id.values())
    merged.sort(key=lambda x: x.hybrid_score, reverse=True)
    return merged
