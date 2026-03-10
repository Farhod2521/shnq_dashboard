from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.clause import Clause
from app.models.clause_embedding import ClauseEmbedding
from app.services.qdrant_service import search_clause_ids


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")


@dataclass
class RetrievedClause:
    clause_id: str
    shnq_code: str
    title: str
    snippet: str
    dense_score: float = 0.0
    lexical_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [w.lower() for w in WORD_RE.findall(text) if len(w) > 2]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def retrieve_dense_clauses(
    db: Session,
    query_vec: list[float],
    document_code: str | None,
    limit: int,
) -> list[RetrievedClause]:
    if not query_vec:
        return []

    hits = search_clause_ids(query_vec, limit=limit, shnq_code=document_code)
    if not hits:
        return []

    ids = [item_id for item_id, _ in hits]
    rows = (
        db.query(ClauseEmbedding)
        .options(joinedload(ClauseEmbedding.clause))
        .filter(ClauseEmbedding.clause_id.in_(ids))
        .all()
    )
    emb_by_clause = {str(row.clause_id): row for row in rows}

    out: list[RetrievedClause] = []
    for clause_id, qdrant_score in hits:
        emb = emb_by_clause.get(clause_id)
        if not emb or not emb.clause:
            continue
        out.append(
            RetrievedClause(
                clause_id=clause_id,
                shnq_code=emb.shnq_code,
                title=f"Band {emb.clause_number or '-'}",
                snippet=(emb.clause.text or "")[:900],
                dense_score=float(qdrant_score),
                signals={"qdrant": float(qdrant_score)},
            )
        )
    return out


def retrieve_lexical_clauses(
    db: Session,
    query: str,
    document_code: str | None,
    limit: int,
) -> list[RetrievedClause]:
    terms = _tokenize(query)
    if not terms:
        return []

    unique_terms = list(dict.fromkeys(terms))[:8]
    ilike_filters = [Clause.text.ilike(f"%{term}%") for term in unique_terms]

    db_q = db.query(Clause).options(joinedload(Clause.document))
    if document_code:
        db_q = db_q.filter(Clause.document.has(code=document_code))
    db_q = db_q.filter(or_(*ilike_filters)).limit(max(limit * 8, 80))

    rows = db_q.all()
    results: list[RetrievedClause] = []
    for row in rows:
        text = row.text or ""
        text_l = text.lower()
        tf = sum(text_l.count(term) for term in unique_terms)
        coverage = sum(1 for term in unique_terms if term in text_l)
        if tf <= 0:
            continue
        score = (coverage * 1.5) + math.log1p(tf)
        results.append(
            RetrievedClause(
                clause_id=str(row.id),
                shnq_code=row.document.code if row.document else "",
                title=f"Band {row.clause_number or '-'}",
                snippet=text[:900],
                lexical_score=float(score),
                signals={"coverage": float(coverage), "tf": float(tf)},
            )
        )

    results.sort(key=lambda x: x.lexical_score, reverse=True)
    return results[:limit]


def retrieve_db_dense_fallback(
    db: Session,
    query_vec: list[float],
    document_code: str | None,
    limit: int,
) -> list[RetrievedClause]:
    if not query_vec:
        return []

    db_q = db.query(ClauseEmbedding).options(joinedload(ClauseEmbedding.clause))
    if document_code:
        db_q = db_q.filter(ClauseEmbedding.shnq_code == document_code)
    rows = db_q.limit(max(limit * 12, 120)).all()

    results: list[RetrievedClause] = []
    for emb in rows:
        if not emb.clause:
            continue
        score = _cosine(query_vec, emb.vector or [])
        results.append(
            RetrievedClause(
                clause_id=str(emb.clause_id),
                shnq_code=emb.shnq_code,
                title=f"Band {emb.clause_number or '-'}",
                snippet=(emb.clause.text or "")[:900],
                dense_score=float(score),
                signals={"db_cosine": float(score)},
            )
        )
    results.sort(key=lambda x: x.dense_score, reverse=True)
    return results[:limit]
