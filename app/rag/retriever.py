from __future__ import annotations

import heapq
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
APOSTROPHE_VARIANTS = str.maketrans({
    "`": "'",
    "\u2019": "'",
    "\u2018": "'",
    "\u02bc": "'",
    "\u02bb": "'",
    "\u2032": "'",
})
PRIORITY_STOPWORDS = {
    "aholi",
    "punkt",
    "punktlar",
    "punktlari",
    "turar",
    "joy",
    "bino",
    "binolar",
    "hudud",
    "hududlar",
    "minimal",
    "maksimal",
    "kamida",
    "kopi",
    "ko'pi",
    "ulush",
    "foiz",
    "masofa",
    "norma",
    "meyor",
    "me'yor",
    "talab",
    "qancha",
    "necha",
    "kerak",
    "bo'lish",
    "bolish",
    "band",
    "bob",
    "hujjat",
}


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
    normalized = repair_mojibake(text).lower().translate(APOSTROPHE_VARIANTS)
    return [_stem_token(w) for w in WORD_RE.findall(normalized) if len(w) > 2]


def _priority_terms(text: str) -> list[str]:
    terms = _tokenize(text)
    candidates = [
        term
        for term in terms
        if len(term) >= 4 and term not in PRIORITY_STOPWORDS
    ]
    if not candidates:
        candidates = [term for term in terms if len(term) >= 5]
    ranked = sorted(dict.fromkeys(candidates), key=len, reverse=True)
    return ranked[:4]


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
    priority_terms = _priority_terms(query)
    doc_codes = _normalize_doc_codes(document_code, document_codes)

    raw_query_terms = [
        _stem_token(token)
        for token in WORD_RE.findall(repair_mojibake(query).lower().translate(APOSTROPHE_VARIANTS))
        if len(token) > 2
    ]
    unique_terms = list(dict.fromkeys([*terms, *raw_query_terms]))[:10]
    priority_search_terms = list(
        dict.fromkeys(
            [
                *priority_terms,
                *[
                    variant
                    for variant in (to_cp1251_mojibake(term) for term in priority_terms)
                    if variant and variant not in priority_terms
                ],
            ]
        )
    )
    mojibake_terms = [
        variant
        for variant in (to_cp1251_mojibake(term) for term in unique_terms)
        if variant and variant not in unique_terms
    ]
    all_search_terms = list(dict.fromkeys([*unique_terms, *mojibake_terms]))
    fetch_limit = max(limit * 40, 1600)
    broad_limit = max(limit * 70, 3200)

    def _fetch_rows(search_terms: list[str]) -> list[Clause]:
        if not search_terms:
            return []
        ilike_filters = [Clause.text.ilike(f"%{term}%") for term in search_terms]
        db_q = db.query(Clause).options(joinedload(Clause.document), joinedload(Clause.chapter))
        if doc_codes:
            db_q = db_q.filter(Clause.document.has(Document.code.in_(doc_codes)))
        return db_q.filter(or_(*ilike_filters)).order_by(Clause.order).limit(fetch_limit).all()

    rows = _fetch_rows(priority_search_terms or all_search_terms)
    if len(rows) < max(24, limit * 3) and priority_search_terms and priority_search_terms != all_search_terms:
        row_map = {str(row.id): row for row in rows}
        for row in _fetch_rows(all_search_terms):
            row_map.setdefault(str(row.id), row)
        rows = list(row_map.values())
    if len(rows) < max(24, limit * 3):
        broad_q = db.query(Clause).options(joinedload(Clause.document), joinedload(Clause.chapter))
        if doc_codes:
            broad_q = broad_q.filter(Clause.document.has(Document.code.in_(doc_codes)))
        row_map = {str(row.id): row for row in rows}
        for row in broad_q.order_by(Clause.order).limit(broad_limit).all():
            row_map.setdefault(str(row.id), row)
        rows = list(row_map.values())

    results: list[RetrievedClause] = []
    for row in rows:
        text = row.text or ""
        chapter_title = row.chapter.title if row.chapter else ""
        text_fixed = repair_mojibake(f"{chapter_title} {text}").lower().translate(APOSTROPHE_VARIANTS)
        text_raw = text.lower()

        tf_clean = sum(text_fixed.count(term) for term in unique_terms)
        coverage_clean = sum(1 for term in unique_terms if term in text_fixed)
        tf_mojibake = sum(text_raw.count(term) for term in mojibake_terms)
        coverage_mojibake = sum(1 for term in mojibake_terms if term in text_raw)
        priority_tf = sum(text_fixed.count(term) for term in priority_terms)
        priority_coverage = sum(1 for term in priority_terms if term in text_fixed)

        tf = max(tf_clean, tf_mojibake)
        coverage = max(coverage_clean, coverage_mojibake)
        if tf <= 0:
            continue
        if priority_terms and priority_coverage <= 0 and coverage < 2:
            continue
        score = (
            (priority_coverage * 3.0)
            + (coverage * 1.15)
            + min(1.0, math.log1p(priority_tf) * 0.45)
            + min(0.6, math.log1p(tf) * 0.18)
        )
        if priority_terms and priority_coverage == len(priority_terms):
            score += 0.45
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
    query_text: str | None,
    document_code: str | None,
    limit: int,
    document_codes: list[str] | None = None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievedClause]:
    if not query_vec:
        return []
    doc_codes = _normalize_doc_codes(document_code, document_codes)
    lexical_limit = max(limit * 30, 900)
    lexical_seed = retrieve_lexical_clauses(
        db=db,
        query=query_text or "",
        document_code=document_code,
        document_codes=document_codes,
        metadata_filters=metadata_filters,
        limit=lexical_limit,
    )
    candidate_ids = [item.clause_id for item in lexical_seed if item.clause_id]
    if not candidate_ids:
        return []

    db_q = db.query(ClauseEmbedding).options(
        joinedload(ClauseEmbedding.clause).joinedload(Clause.document),
        joinedload(ClauseEmbedding.clause).joinedload(Clause.chapter),
    ).filter(ClauseEmbedding.clause_id.in_(candidate_ids))

    heap: list[tuple[float, int, RetrievedClause]] = []
    ordinal = 0
    for emb in db_q.yield_per(256):
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
        if not match_item_filters(item, metadata_filters):
            continue
        if len(heap) < max(limit, 1):
            heapq.heappush(heap, (float(score), ordinal, item))
        elif float(score) > heap[0][0]:
            heapq.heapreplace(heap, (float(score), ordinal, item))
        ordinal += 1

    results = [item for _score, _ordinal, item in sorted(heap, key=lambda x: x[0], reverse=True)]
    return results[:limit]
