from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.rag.reference_parser import extract_document_codes
from app.rag.retriever import RetrievedClause, retrieve_dense_clauses, retrieve_lexical_clauses


WORD_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF']+")
APOSTROPHE_VARIANTS = str.maketrans({
    "`": "'",
    "\u2019": "'",
    "\u2018": "'",
    "\u02bc": "'",
    "\u02bb": "'",
    "\u2032": "'",
})


def _normalize(text: str) -> str:
    lowered = (text or "").strip().lower().translate(APOSTROPHE_VARIANTS)
    return " ".join(lowered.split())


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
        "lariga",
        "sigacha",
        "igacha",
        "sidan",
        "idan",
        "gacha",
        "lari",
        "ning",
        "dagi",
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


def _extract_terms(text: str) -> list[str]:
    values = [_stem_token(token) for token in WORD_RE.findall(_normalize(text))]
    out: list[str] = []
    for token in values:
        if len(token) <= 2:
            continue
        out.append(token)
    uniq: list[str] = []
    seen: set[str] = set()
    for token in out:
        if token in seen:
            continue
        seen.add(token)
        uniq.append(token)
    return uniq[:8]


@dataclass(slots=True)
class DocumentRouteResult:
    document_codes: list[str]
    debug: dict[str, object]


def _aggregate_doc_scores(items: list[RetrievedClause], field: str) -> dict[str, float]:
    bucket: dict[str, list[float]] = {}
    for item in items:
        code = (item.shnq_code or "").strip()
        if not code:
            continue
        score = float(getattr(item, field, 0.0) or 0.0)
        if score <= 0:
            continue
        bucket.setdefault(code, []).append(score)

    out: dict[str, float] = {}
    for code, scores in bucket.items():
        ranked = sorted(scores, reverse=True)
        top = ranked[0]
        mean_top = sum(ranked[:3]) / min(3, len(ranked))
        # Hujjat ichida ko'p bo'lakli umumiy shovqinni emas, eng kuchli mos bandni ustun qo'yamiz.
        out[code] = (top * 0.72) + (mean_top * 0.28)
    return out


def route_documents(
    db: Session,
    query: str,
    query_vec: list[float],
    requested_doc_code: str | None = None,
    explicit_doc_codes: list[str] | None = None,
) -> DocumentRouteResult:
    explicit = [code.strip() for code in (explicit_doc_codes or []) if code and code.strip()]
    if requested_doc_code and requested_doc_code.strip():
        explicit = [requested_doc_code.strip(), *explicit]
    explicit_l = {value.lower() for value in explicit}
    if explicit:
        ordered = []
        seen: set[str] = set()
        for code in explicit:
            key = code.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(code)
        return DocumentRouteResult(
            document_codes=ordered,
            debug={"mode": "explicit", "document_codes": ordered},
        )

    terms = _extract_terms(query)
    lexical_scores: dict[str, float] = {}
    if terms:
        filters = [Document.title.ilike(f"%{term}%") for term in terms[:5]]
        rows = db.query(Document).filter(or_(*filters)).limit(120).all()
        for row in rows:
            haystack = _normalize(f"{row.code} {row.title}")
            coverage = sum(1 for term in terms if term in haystack)
            tf = sum(haystack.count(term) for term in terms)
            if coverage <= 0:
                continue
            lexical_scores[row.code] = float((coverage * 0.8) + min(0.6, math.log1p(tf) * 0.3))

    dense_scores: dict[str, float] = {}
    dense_hits = retrieve_dense_clauses(
        db=db,
        query_vec=query_vec,
        document_code=None,
        limit=max(settings.RAG_DENSE_K, settings.RAG_DOC_ROUTE_DENSE_K),
    )
    if not dense_hits:
        from app.rag.retriever import retrieve_db_dense_fallback

        dense_hits = retrieve_db_dense_fallback(
            db=db,
            query_vec=query_vec,
            document_code=None,
            limit=max(settings.RAG_DENSE_K, settings.RAG_DOC_ROUTE_DENSE_K),
        )
    dense_scores = _aggregate_doc_scores(dense_hits, "dense_score")

    lexical_scores_from_clauses: dict[str, float] = {}
    lexical_hits = retrieve_lexical_clauses(
        db=db,
        query=query,
        document_code=None,
        limit=max(settings.RAG_DOC_ROUTE_DENSE_K, settings.RAG_LEXICAL_K),
    )
    lexical_scores_from_clauses = _aggregate_doc_scores(lexical_hits, "lexical_score")

    score_map: dict[str, float] = {}
    for code, score in dense_scores.items():
        score_map[code] = score_map.get(code, 0.0) + (score * 0.78)
    for code, score in lexical_scores.items():
        score_map[code] = score_map.get(code, 0.0) + (score * 0.35)
    for code, score in lexical_scores_from_clauses.items():
        score_map[code] = score_map.get(code, 0.0) + (score * 0.55)

    inferred_codes = extract_document_codes(query)
    for code in inferred_codes:
        score_map[code] = score_map.get(code, 0.0) + 1.6

    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
    selected_codes = [code for code, score in ranked if score >= settings.RAG_DOC_ROUTE_MIN_SCORE][: settings.RAG_DOC_ROUTE_TOP_K]

    # Noto'g'ri hujjatga qattiq yopishib qolmaslik uchun yaqin ikkinchi hujjatni ham qamrab olamiz.
    if len(selected_codes) < settings.RAG_DOC_ROUTE_TOP_K and ranked:
        top_score = ranked[0][1]
        for code, score in ranked:
            if code in selected_codes:
                continue
            if score >= max(settings.RAG_DOC_ROUTE_MIN_SCORE * 0.92, top_score - 0.08):
                selected_codes.append(code)
            if len(selected_codes) >= settings.RAG_DOC_ROUTE_TOP_K:
                break

    if not selected_codes and inferred_codes:
        selected_codes = inferred_codes[: settings.RAG_DOC_ROUTE_TOP_K]

    # Fallback keeps backward compatibility if route step is uncertain.
    if not selected_codes:
        selected_codes = [code for code, _ in ranked[: settings.RAG_DOC_ROUTE_TOP_K]]

    return DocumentRouteResult(
        document_codes=selected_codes,
        debug={
            "mode": "scored",
            "terms": terms,
            "explicit_query_codes": inferred_codes,
            "scores": [{"code": code, "score": round(score, 5)} for code, score in ranked[:10]],
            "selected": selected_codes,
            "dense_doc_scores": {code: round(score, 5) for code, score in dense_scores.items()},
            "lexical_doc_scores": {code: round(score, 5) for code, score in lexical_scores.items()},
            "clause_lexical_doc_scores": {code: round(score, 5) for code, score in lexical_scores_from_clauses.items()},
            "explicit_input_codes": list(explicit_l),
        },
    )
