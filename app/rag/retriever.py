from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.clause import Clause
from app.models.clause_embedding import ClauseEmbedding
from app.models.document import Document
from app.rag.metadata_filter import MetadataFilters, match_item_filters
from app.services.qdrant_service import search_clause_ids
from app.utils.text_fix import repair_mojibake, to_cp1251_mojibake


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")
logger = logging.getLogger(__name__)


@dataclass
class RetrievedClause:
    clause_id: str
    shnq_code: str
    title: str
    snippet: str
    clause_number: str | None = None
    document_id: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    page: str | None = None
    language: str | None = "uz"
    content_type: str | None = "clause"
    dense_score: float = 0.0
    lexical_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    normalized = repair_mojibake(text)
    return [w.lower() for w in WORD_RE.findall(normalized) if len(w) > 2]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _normalize_doc_codes(document_code: str | None, document_codes: list[str] | None) -> list[str]:
    values = [code for code in (document_codes or []) if code and code.strip()]
    if document_code and document_code.strip():
        values.insert(0, document_code.strip())
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out


def _qdrant_metadata_filters(filters: MetadataFilters | None) -> dict[str, list[str]] | None:
    if not filters:
        return None
    f = filters.normalized()
    out: dict[str, list[str]] = {}
    if f.document_ids:
        out["document_id"] = f.document_ids
    if f.section_ids:
        out["section_id"] = f.section_ids
    if f.clause_numbers:
        out["clause_number"] = f.clause_numbers
    if f.languages:
        out["language"] = f.languages
    if f.content_types:
        out["content_type"] = f.content_types
    if f.pages:
        out["page"] = f.pages
    return out or None


def retrieve_dense_clauses(
    db: Session,
    query_vec: list[float],
    document_code: str | None,
    limit: int,
    document_codes: list[str] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievedClause]:
    if not query_vec:
        return []
    doc_codes = _normalize_doc_codes(document_code, document_codes)

    hits = search_clause_ids(
        query_vec,
        limit=limit,
        shnq_code=doc_codes[0] if len(doc_codes) == 1 else None,
        shnq_codes=doc_codes if len(doc_codes) > 1 else None,
        metadata_filters=_qdrant_metadata_filters(metadata_filters),
    )
    if not hits:
        return []

    ids = [item_id for item_id, _ in hits]
    rows = (
        db.query(ClauseEmbedding)
        .options(
            joinedload(ClauseEmbedding.clause).joinedload(Clause.document),
            joinedload(ClauseEmbedding.clause).joinedload(Clause.chapter),
        )
        .filter(ClauseEmbedding.clause_id.in_(ids))
        .all()
    )
    emb_by_clause = {str(row.clause_id): row for row in rows}

    out: list[RetrievedClause] = []
    for clause_id, qdrant_score in hits:
        emb = emb_by_clause.get(clause_id)
        if not emb or not emb.clause:
            continue
        row = emb.clause
        item = RetrievedClause(
            clause_id=clause_id,
            shnq_code=emb.shnq_code,
            title=f"Band {emb.clause_number or row.clause_number or '-'}",
            snippet=(row.text or "")[:900],
            clause_number=emb.clause_number or row.clause_number,
            document_id=str(row.document_id) if row.document_id else None,
            section_id=str(row.chapter_id) if row.chapter_id else None,
            section_title=emb.chapter_title or (row.chapter.title if row.chapter else None),
            content_type="clause",
            language="uz",
            dense_score=float(qdrant_score),
            signals={"qdrant": float(qdrant_score)},
        )
        if match_item_filters(item, metadata_filters):
            out.append(item)
    logger.debug("dense retrieval completed: total=%s filtered=%s docs=%s", len(hits), len(out), doc_codes)
    return out


def retrieve_lexical_clauses(
    db: Session,
    query: str,
    document_code: str | None,
    limit: int,
    document_codes: list[str] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievedClause]:
    terms = _tokenize(query)
    if not terms:
        return []
    doc_codes = _normalize_doc_codes(document_code, document_codes)

    unique_terms = list(dict.fromkeys(terms))[:8]
    mojibake_terms = [
        variant
        for variant in (to_cp1251_mojibake(term) for term in unique_terms)
        if variant and variant not in unique_terms
    ]
    search_terms = list(dict.fromkeys([*unique_terms, *mojibake_terms]))
    ilike_filters = [Clause.text.ilike(f"%{term}%") for term in search_terms]

    db_q = db.query(Clause).options(joinedload(Clause.document), joinedload(Clause.chapter))
    if doc_codes:
        db_q = db_q.filter(Clause.document.has(Document.code.in_(doc_codes)))
    db_q = db_q.filter(or_(*ilike_filters)).limit(max(limit * 12, 120))

    rows = db_q.all()
    if len(rows) < max(24, limit * 3):
        broad_q = db.query(Clause).options(joinedload(Clause.document), joinedload(Clause.chapter))
        if doc_codes:
            broad_q = broad_q.filter(Clause.document.has(Document.code.in_(doc_codes)))
        fallback_rows = broad_q.limit(max(limit * 60, 2400)).all()
        row_map = {str(row.id): row for row in rows}
        for row in fallback_rows:
            row_map.setdefault(str(row.id), row)
        rows = list(row_map.values())

    results: list[RetrievedClause] = []
    for row in rows:
        text = row.text or ""
        text_fixed = repair_mojibake(text).lower()
        text_raw = text.lower()

        tf_clean = sum(text_fixed.count(term) for term in unique_terms)
        coverage_clean = sum(1 for term in unique_terms if term in text_fixed)
        tf_mojibake = sum(text_raw.count(term) for term in mojibake_terms)
        coverage_mojibake = sum(1 for term in mojibake_terms if term in text_raw)

        tf = max(tf_clean, tf_mojibake)
        coverage = max(coverage_clean, coverage_mojibake)
        if tf <= 0:
            continue
        score = (coverage * 1.5) + math.log1p(tf)
        item = RetrievedClause(
            clause_id=str(row.id),
            shnq_code=row.document.code if row.document else "",
            title=f"Band {row.clause_number or '-'}",
            snippet=text[:900],
            clause_number=row.clause_number,
            document_id=str(row.document_id) if row.document_id else None,
            section_id=str(row.chapter_id) if row.chapter_id else None,
            section_title=row.chapter.title if row.chapter else None,
            content_type="clause",
            language="uz",
            lexical_score=float(score),
            signals={"coverage": float(coverage), "tf": float(tf)},
        )
        if match_item_filters(item, metadata_filters):
            results.append(item)

    results.sort(key=lambda x: x.lexical_score, reverse=True)
    return results[:limit]


def retrieve_db_dense_fallback(
    db: Session,
    query_vec: list[float],
    document_code: str | None,
    limit: int,
    document_codes: list[str] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievedClause]:
    if not query_vec:
        return []
    doc_codes = _normalize_doc_codes(document_code, document_codes)

    db_q = db.query(ClauseEmbedding).options(
        joinedload(ClauseEmbedding.clause).joinedload(Clause.document),
        joinedload(ClauseEmbedding.clause).joinedload(Clause.chapter),
    )
    if doc_codes:
        db_q = db_q.filter(ClauseEmbedding.shnq_code.in_(doc_codes))
    rows = db_q.limit(max(limit * 12, 120)).all()

    results: list[RetrievedClause] = []
    for emb in rows:
        if not emb.clause:
            continue
        if not emb.vector or len(emb.vector) != len(query_vec):
            continue
        score = _cosine(query_vec, emb.vector or [])
        row = emb.clause
        item = RetrievedClause(
            clause_id=str(emb.clause_id),
            shnq_code=emb.shnq_code,
            title=f"Band {emb.clause_number or '-'}",
            snippet=(row.text or "")[:900],
            clause_number=emb.clause_number or row.clause_number,
            document_id=str(row.document_id) if row.document_id else None,
            section_id=str(row.chapter_id) if row.chapter_id else None,
            section_title=emb.chapter_title or (row.chapter.title if row.chapter else None),
            content_type="clause",
            language="uz",
            dense_score=float(score),
            signals={"db_cosine": float(score)},
        )
        if match_item_filters(item, metadata_filters):
            results.append(item)
    results.sort(key=lambda x: x.dense_score, reverse=True)
    return results[:limit]
