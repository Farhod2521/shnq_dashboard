from __future__ import annotations

import copy
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.clause import Clause
from app.models.document import Document
from app.models.image_embedding import ImageEmbedding
from app.models.norm_image import NormImage
from app.models.norm_table import NormTable
from app.models.norm_table_cell import NormTableCell
from app.models.norm_table_row import NormTableRow
from app.models.question_answer import QuestionAnswer
from app.models.table_row_embedding import TableRowEmbedding
from app.rag.hybrid_search import reciprocal_rank_fusion
from app.rag.re_ranker import rerank_clauses
from app.rag.retriever import retrieve_db_dense_fallback, retrieve_dense_clauses, retrieve_lexical_clauses
from app.services.llm_service import (
    detect_query_language,
    embed_text,
    ensure_answer_language,
    generate_answer,
    generate_text,
    translate_query_for_search,
)


DOCUMENT_CODE_RE = re.compile(r"\b(shnq|qmq|kmk|snip)\s*([0-9][0-9.\-]*)\b", re.IGNORECASE)
TABLE_NUMBER_RE = re.compile(
    r"(?:\bjadval(?:da|ni|ga|dan|ning|lar)?\s*[-.]?\s*(\d+(?:\.\d+)*[a-z]?)\b|"
    r"\b(\d+(?:\.\d+)*[a-z]?)\s*[-.]?\s*jadval(?:da|ni|ga|dan|ning|lar)?\b)",
    re.IGNORECASE,
)
APPENDIX_NUMBER_RE = re.compile(
    r"(?:\b(\d+)\s*[-.]?\s*ilova(?:si|da|ga|dan|ning|lar)?\b|"
    r"\bilova(?:si|da|ga|dan|ning|lar)?\s*[-.]?\s*(\d+)\b)",
    re.IGNORECASE,
)
TABLE_TYPO_RE = re.compile(r"\b(jadval|jadvl|jadvlda|jdval|table|ilova|appendix)\b", re.IGNORECASE)
GREETING_PATTERNS = [
    r"\bsalom\b",
    r"\bassalomu?\s+alaykum\b",
    r"\bva\s*alaykum\s+assalom\b",
    r"\bhello\b",
    r"\bhi\b",
]
SHNQ_KEYWORDS = [
    "shnq",
    "qmq",
    "kmk",
    "snip",
    "qurilish",
    "me'yor",
    "meyor",
    "norma",
    "band",
    "bob",
    "hujjat",
]
OUT_OF_SCOPE_KEYWORDS = [
    "python",
    "javascript",
    "react",
    "nextjs",
    "fastapi",
    "django",
    "sport",
    "music",
    "kino",
    "weather",
]
TABLE_HINTS = ["jadval", "table", "ilova", "appendix"]
IMAGE_URL_RE = re.compile(r"\bURL:\s*(https?://\S+)", re.IGNORECASE)
TABLE_QUESTION_HINTS = {"nima", "qanday", "qancha", "necha", "qaysi", "izoh", "tushuntir", "hisobla", "ber", "kerak"}
ROW_FOCUS_TERMS = {
    "deraza",
    "eshik",
    "lift",
    "fasad",
    "tom",
    "issiqlik",
    "material",
    "rang",
    "o'lcham",
    "quvvat",
    "talab",
}
QUERY_STOPWORDS = {
    "uchun",
    "bilan",
    "qanday",
    "qaysi",
    "nima",
    "emas",
    "keltirilgan",
    "berilgan",
    "bo'lgan",
    "bolgan",
    "shnq",
    "qmq",
    "kmk",
    "snip",
    "larda",
    "larda?",
}
APOSTROPHE_VARIANTS = str.maketrans({
    "`": "'",
    "\u2019": "'",
    "\u2018": "'",
    "\u02bc": "'",
    "\u02bb": "'",
    "\u2032": "'",
})
CLARIFICATION_RULES = [
    ("missing_parameter", "Aniq qaysi parametr haqida?"),
    ("missing_comparison_target", "Qaysi ikki talabni solishtirmoqchisiz?"),
    ("missing_use_case", "Aynan qaysi holat uchun? (masalan: turar joy, jamoat binosi yoki yong'in xavfsizligi)"),
]

_FEWSHOT_CACHE: list[dict[str, str]] | None = None
_FEWSHOT_VECTOR_CACHE: list[tuple[dict[str, str], list[float]]] | None = None


@dataclass
class RetrievalItem:
    kind: str
    score: float
    title: str
    snippet: str
    shnq_code: str
    clause_id: str | None = None
    table_id: str | None = None
    table_number: str | None = None
    image_id: str | None = None
    chapter: str | None = None
    clause_number: str | None = None
    html_anchor: str | None = None
    lex_url: str | None = None
    image_url: str | None = None
    appendix_number: str | None = None
    row_index: int | None = None
    semantic_score: float | None = None
    keyword_score: float | None = None


def _normalize_text(text: str) -> str:
    lowered = unicodedata.normalize("NFKC", (text or "")).strip().lower()
    lowered = lowered.translate(APOSTROPHE_VARIANTS)
    return re.sub(r"\s+", " ", lowered)


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_greeting(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(re.search(pattern, normalized) for pattern in GREETING_PATTERNS)


def _is_shnq_related(text: str) -> bool:
    return _contains_any(_normalize_text(text), SHNQ_KEYWORDS)


def _is_clearly_out_of_scope(text: str) -> bool:
    return _contains_any(_normalize_text(text), OUT_OF_SCOPE_KEYWORDS)


def _build_greeting_response() -> str:
    return "Assalomu alaykum! SHNQ bo'yicha qanday savolingiz bor?"


def _build_out_of_scope_response() -> str:
    return (
        "Kechirasiz, men faqat SHNQ (qurilish me'yorlari) bo'yicha savollarga javob bera olaman. "
        "Iltimos, savolingizni SHNQ hujjati, bob yoki bandga bog'lab yozing."
    )


def _extract_doc_code(text: str) -> str | None:
    match = DOCUMENT_CODE_RE.search(_normalize_text(text))
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"


def _extract_table_number(text: str) -> str | None:
    match = TABLE_NUMBER_RE.search(_normalize_text(text))
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip().replace(",", ".")


def _normalize_table_reference(value: str | None) -> str:
    return re.sub(r"[\s,\-]+", ".", (value or "").strip().lower()).strip(".")


def _table_reference_variants(table_number: str) -> list[str]:
    normalized = _normalize_table_reference(table_number)
    if not normalized:
        return []
    variants = [
        normalized,
        normalized.replace(".", "-"),
        normalized.replace(".", ","),
        normalized.replace(".", ""),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _match_table_number(value: str | None, target: str) -> bool:
    source = _normalize_table_reference(value)
    wanted = _normalize_table_reference(target)
    return bool(source and wanted and source == wanted)


def _extract_appendix_number(text: str) -> str | None:
    match = APPENDIX_NUMBER_RE.search(_normalize_text(text))
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip()


def _is_table_request(text: str) -> bool:
    normalized = _normalize_text(text)
    has_doc = _extract_doc_code(normalized) is not None
    has_table_num = _extract_table_number(normalized) is not None
    has_appendix_num = _extract_appendix_number(normalized) is not None
    has_table_word = bool(TABLE_TYPO_RE.search(normalized))
    return (
        (has_doc and (has_table_num or has_appendix_num))
        or (has_table_num and has_table_word)
        or (has_appendix_num and has_table_word)
        or any(hint in normalized for hint in TABLE_HINTS)
    )


def _is_table_direct_lookup_request(message: str) -> bool:
    normalized = _normalize_text(message)
    if "?" in (message or ""):
        return False
    return not any(hint in normalized for hint in TABLE_QUESTION_HINTS)


def _build_table_answer(table: NormTable) -> str:
    chapter_title = table.section_title or (table.chapter.title if table.chapter else "-")
    return f"{table.document.code if table.document else ''} bo'yicha {table.table_number} topildi ({chapter_title})."


def _find_tables_by_reference(
    db: Session,
    table_number: str,
    doc_code: str | None = None,
) -> list[NormTable]:
    variants = _table_reference_variants(table_number)
    if not variants:
        return []

    query = db.query(NormTable).options(joinedload(NormTable.document), joinedload(NormTable.chapter))
    filters = [NormTable.table_number.ilike(variant) for variant in variants]
    for variant in variants:
        filters.extend(
            [
                NormTable.title.ilike(f"%{variant}%"),
                NormTable.markdown.ilike(f"%{variant}%"),
                NormTable.raw_html.ilike(f"%{variant}%"),
            ]
        )

    candidates = query.filter(or_(*filters)).all()
    candidates = [
        item
        for item in candidates
        if _match_table_number(item.table_number, table_number)
        or any(
            variant.lower() in (item.title or "").lower()
            or variant.lower() in (item.markdown or "").lower()
            or variant.lower() in (item.raw_html or "").lower()
            for variant in variants
        )
    ]
    if doc_code:
        key = re.sub(r"\s+", "", doc_code).lower()
        candidates = [c for c in candidates if c.document and key in re.sub(r"\s+", "", c.document.code).lower()]

    unique: list[NormTable] = []
    seen_ids: set[str] = set()
    for item in candidates:
        item_id = str(item.id)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        unique.append(item)
    return unique


def _find_table_for_query(
    db: Session,
    message: str,
    doc_code_hint: str | None = None,
) -> tuple[NormTable | None, str | None, str | None, list[NormTable]]:
    table_number = _extract_table_number(message)
    appendix_number = _extract_appendix_number(message)
    if not table_number and appendix_number:
        table_number = f"ilova-{appendix_number}"
    doc_code = doc_code_hint or _extract_doc_code(message)
    if not table_number:
        return None, table_number, doc_code, []
    candidates = _find_tables_by_reference(db, table_number, doc_code)
    if not candidates:
        return None, table_number, doc_code, []
    if len(candidates) == 1:
        return candidates[0], table_number, doc_code, candidates
    return None, table_number, doc_code, candidates


def _table_candidate_docs(db: Session, table_number: str) -> list[str]:
    rows = _find_tables_by_reference(db, table_number)
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        code = row.document.code if row.document else ""
        key = code.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(code)
        if len(out) >= 7:
            break
    return out


def _table_candidate_chapters(candidates: list[NormTable]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        chapter = item.section_title or (item.chapter.title if item.chapter else "Noma'lum bob")
        key = (chapter or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(chapter)
        if len(out) >= 6:
            break
    return out


def _needs_clarification(text: str) -> tuple[str, str] | None:
    normalized = _normalize_text(text)
    if _is_document_list_request(normalized):
        return None
    if re.search(r"\b(qancha|necha|minimal|maksimal|me'yor|meyor)\b", normalized) and not re.search(r"\d", normalized):
        return CLARIFICATION_RULES[0]
    if any(k in normalized for k in ["taqqos", "solishtir", "farqi"]) and " va " not in normalized:
        return CLARIFICATION_RULES[1]
    if any(k in normalized for k in ["eshik", "deraza", "zina", "evakuatsiya"]) and not any(
        k in normalized for k in ["turar joy", "jamoat", "sanoat", "ombor"]
    ):
        return CLARIFICATION_RULES[2]
    return None


def _stem_query_token(token: str) -> str:
    value = token.lower()
    for suffix in ("lardan", "larning", "larga", "larni", "ning", "dan", "ga", "da", "ni", "lar", "si", "i"):
        if value.endswith(suffix) and len(value) - len(suffix) >= 4:
            return value[: -len(suffix)]
    return value


def _is_table_row_priority_query(text: str) -> bool:
    normalized = _normalize_text(text)
    if any(phrase in normalized for phrase in ("qaysi shnq", "qaysi hujjat", "qaysi norma", "qaysi normativ")):
        return True
    has_focus_term = any(term in normalized for term in ROW_FOCUS_TERMS)
    has_question_intent = any(word in normalized for word in ("qaysi", "qanday", "keltirilgan", "berilgan", "talab"))
    return has_focus_term and has_question_intent


def _extract_document_codes(text: str) -> list[str]:
    normalized = _normalize_text(text)
    out: list[str] = []
    seen: set[str] = set()
    for match in DOCUMENT_CODE_RE.finditer(normalized):
        code = f"{match.group(1).upper()} {match.group(2)}"
        key = code.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(code)
    return out


def _is_document_list_request(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(phrase in normalized for phrase in ("qaysi shnq", "qaysi hujjat", "qaysi norma", "qaysi normativ"))


def _format_document_options(docs: list[str], title_by_code: dict[str, str] | None = None) -> str:
    mapping = title_by_code or {}
    lines: list[str] = []
    for idx, code in enumerate(docs, start=1):
        title = mapping.get(code.lower())
        if title:
            lines.append(f"{idx}. {code} - {title}")
        else:
            lines.append(f"{idx}. {code}")
    return "\n".join(lines)


def _build_document_list_answer(
    codes: list[str],
    response_language: str,
    title_by_code: dict[str, str] | None = None,
) -> str:
    detailed_label, short_label = _answer_labels(response_language)
    detail = (
        "Savolga mos quyidagi SHNQ hujjatlarida kerakli javob uchraydi:\n"
        + _format_document_options(codes, title_by_code)
        + "\nAynan qaysi SHNQ nazarda tutilayotganini yozing."
    )
    short = ", ".join(codes[:3])
    if len(codes) > 3:
        short += " va boshqalar."
    else:
        short += "."
    return f"{detailed_label}: {detail}\n{short_label}: {short}"


def _collect_codes_from_items(items: list[RetrievalItem]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        for value in [item.shnq_code, item.snippet]:
            for code in _extract_document_codes(value or ""):
                key = code.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(code)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _extract_query_terms(text: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z\u0400-\u04FF']+", _normalize_text(text))
    out: list[str] = []
    for token in tokens:
        token = _stem_query_token(token)
        if len(token) <= 2 or token in QUERY_STOPWORDS:
            continue
        out.append(token)
    return list(dict.fromkeys(out))[:8]


def _keyword_score(terms: list[str], text: str) -> float:
    haystack = _normalize_text(text)
    if not terms or not haystack:
        return 0.0
    return sum(1 for term in terms if term in haystack) / max(len(terms), 1)


def _search_clause_candidates(db: Session, query: str, query_vec: list[float], doc_code: str | None) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    dense = retrieve_dense_clauses(db=db, query_vec=query_vec, document_code=doc_code, limit=settings.RAG_DENSE_K)
    if not dense:
        dense = retrieve_db_dense_fallback(db=db, query_vec=query_vec, document_code=doc_code, limit=settings.RAG_DENSE_K)
    lexical = retrieve_lexical_clauses(db=db, query=query, document_code=doc_code, limit=settings.RAG_LEXICAL_K)
    fused = reciprocal_rank_fusion(dense, lexical, rrf_k=settings.RAG_RRF_K)
    fused = rerank_clauses(query, fused[: settings.RAG_RERANK_CANDIDATES], settings.RAG_TOP_K) if settings.RAG_ENABLE_RERANK else fused[: settings.RAG_TOP_K]
    return [
        RetrievalItem(
            kind="clause",
            score=item.rerank_score or item.hybrid_score or item.dense_score or item.lexical_score,
            title=item.title,
            snippet=item.snippet,
            shnq_code=item.shnq_code,
            clause_id=item.clause_id,
            semantic_score=item.dense_score,
            keyword_score=_keyword_score(terms, item.snippet),
        )
        for item in fused
    ]


def _search_table_row_candidates(
    db: Session,
    query: str,
    query_vec: list[float],
    doc_code: str | None,
    row_priority: bool = False,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    normalized_query = _normalize_text(query)
    out: list[RetrievalItem] = []
    db_q = db.query(TableRowEmbedding).options(
        joinedload(TableRowEmbedding.row).joinedload(NormTableRow.table).joinedload(NormTable.document),
        joinedload(TableRowEmbedding.row).joinedload(NormTableRow.table).joinedload(NormTable.chapter),
    )
    if doc_code:
        db_q = db_q.filter(TableRowEmbedding.shnq_code == doc_code)
    for emb in db_q.all():
        table = emb.row.table if emb.row else None
        combined_text = " | ".join(
            part
            for part in [
                emb.search_text or "",
                table.title if table and table.title else "",
                table.section_title if table and table.section_title else "",
            ]
            if part
        )
        normalized_row = _normalize_text(combined_text)
        semantic = _cosine(query_vec, emb.vector or [])
        keyword = _keyword_score(terms, normalized_row)
        tf = sum(normalized_row.count(term) for term in terms)
        coverage = sum(1 for term in terms if term in normalized_row)
        phrase_bonus = 0.35 if normalized_query and normalized_query in normalized_row else 0.0
        focus_bonus = 0.12 if row_priority and coverage >= 2 else 0.0
        score = (semantic * 0.85) + (keyword * 0.6) + min(0.35, tf * 0.06) + phrase_bonus + focus_bonus

        # Row-priority querylarda lexical moslik yetarli bo'lsa semantic past bo'lsa ham o'tkazamiz.
        if not row_priority and score < settings.RAG_TABLE_ROW_MIN_SCORE and keyword <= 0:
            continue
        if row_priority and coverage == 0 and semantic < settings.RAG_TABLE_ROW_MIN_SCORE:
            continue

        out.append(
            RetrievalItem(
                kind="table_row",
                score=score,
                title=f"Jadval {emb.table_number} / satr {emb.row_index}",
                snippet=combined_text[:900],
                shnq_code=emb.shnq_code,
                table_id=str(table.id) if table else None,
                table_number=emb.table_number,
                chapter=table.section_title if table and table.section_title else (table.chapter.title if table and table.chapter else None),
                row_index=emb.row_index,
                semantic_score=semantic,
                keyword_score=keyword,
            )
        )
    out.sort(key=lambda x: x.score, reverse=True)
    return out[: max(1, settings.RAG_TABLE_ROW_TOP_K)]


def _search_table_row_keyword_fallback(
    db: Session,
    query: str,
    doc_code: str | None,
    limit: int,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    if not terms:
        return []

    filters = [NormTableCell.text.ilike(f"%{term}%") for term in terms[:6]]
    db_q = (
        db.query(NormTableCell, NormTableRow, NormTable)
        .join(NormTableRow, NormTableCell.row_id == NormTableRow.id)
        .join(NormTable, NormTableRow.table_id == NormTable.id)
        .options(
            joinedload(NormTableRow.table).joinedload(NormTable.document),
            joinedload(NormTableRow.table).joinedload(NormTable.chapter),
            joinedload(NormTableRow.cells),
        )
        .filter(or_(*filters))
    )
    if doc_code:
        db_q = db_q.filter(NormTable.document.has(code=doc_code))

    rows = db_q.limit(max(limit * 50, 600)).all()
    by_row: dict[str, RetrievalItem] = {}
    for _cell, row, table in rows:
        row_id = str(row.id)
        cell_text = " | ".join((c.text or "").strip() for c in row.cells if (c.text or "").strip())
        if not cell_text:
            continue
        normalized = _normalize_text(cell_text)
        tf = sum(normalized.count(term) for term in terms)
        coverage = sum(1 for term in terms if term in normalized)
        if coverage <= 0:
            continue
        score = (coverage * 0.55) + min(0.55, tf * 0.07)
        prev = by_row.get(row_id)
        candidate = RetrievalItem(
            kind="table_row",
            score=score,
            title=f"Jadval {table.table_number} / satr {row.row_index}",
            snippet=cell_text[:900],
            shnq_code=table.document.code if table.document else "",
            table_id=str(table.id),
            table_number=table.table_number,
            chapter=table.section_title or (table.chapter.title if table.chapter else None),
            row_index=row.row_index,
            semantic_score=0.0,
            keyword_score=float(coverage / max(len(terms), 1)),
        )
        if not prev or candidate.score > prev.score:
            by_row[row_id] = candidate

    out = list(by_row.values())
    out.sort(key=lambda x: x.score, reverse=True)
    return out[: max(limit, 1)]


def _search_image_candidates(db: Session, query: str, query_vec: list[float], doc_code: str | None) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    out: list[RetrievalItem] = []
    db_q = db.query(ImageEmbedding).options(
        joinedload(ImageEmbedding.image).joinedload(NormImage.document),
        joinedload(ImageEmbedding.image).joinedload(NormImage.chapter),
    )
    if doc_code:
        db_q = db_q.filter(ImageEmbedding.shnq_code == doc_code)
    for emb in db_q.all():
        image = emb.image
        context = " | ".join([p for p in [image.title if image else "", image.context_text if image else "", image.ocr_text if image else "", f"URL: {image.image_url}" if image else ""] if p])
        semantic = _cosine(query_vec, emb.vector or [])
        keyword = _keyword_score(terms, context)
        score = semantic + (settings.RAG_KEYWORD_WEIGHT * keyword)
        if score < settings.RAG_IMAGE_MIN_SCORE and keyword <= 0:
            continue
        out.append(
            RetrievalItem(
                kind="image",
                score=score,
                title=f"Rasm {emb.appendix_number or ''}".strip(),
                snippet=context[:900],
                shnq_code=emb.shnq_code,
                image_id=str(emb.image_id) if emb.image_id else None,
                chapter=emb.chapter_title,
                appendix_number=emb.appendix_number,
                html_anchor=image.html_anchor if image else None,
                image_url=image.image_url if image else emb.image_url,
                semantic_score=semantic,
                keyword_score=keyword,
            )
        )
    out.sort(key=lambda x: x.score, reverse=True)
    return out[: max(1, settings.RAG_IMAGE_TOP_K)]


def _rewrite_query_if_needed(question: str) -> str:
    if not settings.RAG_REWRITE_QUERY:
        return question
    try:
        prompt = (
            "Quyidagi savolni SHNQ qidiruvi uchun qisqa va aniq qidiruv so'rovi sifatida qayta yozing. "
            "Kodlar, raqamlar, birliklar o'zgarmasin.\n\n"
            f"{question}\n\nQidiruv so'rovi:"
        )
        rewritten = generate_text(prompt=prompt, system="Faqat bitta qidiruv jumlasini qaytaring.", model=settings.CHAT_MODEL, options={"temperature": 0.0, "top_p": 0.9, "max_tokens": settings.RAG_REWRITE_MAX_TOKENS})
        return (rewritten or question).strip()
    except Exception:
        return question


def _load_fewshot() -> list[dict[str, str]]:
    global _FEWSHOT_CACHE
    if _FEWSHOT_CACHE is not None:
        return _FEWSHOT_CACHE
    if not settings.RAG_FEWSHOT_ENABLED:
        _FEWSHOT_CACHE = []
        return _FEWSHOT_CACHE
    file_path = Path(settings.RAG_FEWSHOT_FILE)
    if not file_path.exists():
        _FEWSHOT_CACHE = []
        return _FEWSHOT_CACHE
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        _FEWSHOT_CACHE = []
        return _FEWSHOT_CACHE
    cleaned: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        question = (item.get("question") or "").strip()
        answer = (item.get("answer") or "").strip()
        if question and answer:
            cleaned.append({"question": question, "answer": answer})
    _FEWSHOT_CACHE = cleaned
    return _FEWSHOT_CACHE


def _pick_fewshot_examples(question: str, limit: int = 3) -> list[dict[str, str]]:
    global _FEWSHOT_VECTOR_CACHE
    data = _load_fewshot()
    if not data:
        return []
    q_vec = embed_text(question)
    if not q_vec:
        return data[: max(limit, 1)]
    if _FEWSHOT_VECTOR_CACHE is None:
        prepared: list[tuple[dict[str, str], list[float]]] = []
        for item in data:
            vec = embed_text(item["question"])
            if vec:
                prepared.append((item, vec))
        _FEWSHOT_VECTOR_CACHE = prepared
    scored = [(_cosine(q_vec, vec), item) for item, vec in (_FEWSHOT_VECTOR_CACHE or []) if vec]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[: max(limit, 1)]] if scored else data[: max(limit, 1)]


def _answer_labels(response_language: str = "uz") -> tuple[str, str]:
    if response_language == "en":
        return "Details", "In short"
    if response_language == "ru":
        return "Details", "In short"
    if response_language == "ko":
        return "Details", "In short"
    return "Batafsil", "Qisqa qilib aytganda"


def _empty_answer_text(response_language: str = "uz") -> str:
    if response_language == "en":
        return "No clear answer was found in the context."
    if response_language in {"ru", "ko"}:
        return "No clear answer was found in the context."
    return "Kontekstda aniq javob topilmadi."


def _cleanup_answer_format(answer: str, response_language: str = "uz") -> str:
    text = (answer or "").strip()
    if not text:
        return _empty_answer_text(response_language)
    detailed_label, short_label = _answer_labels(response_language)
    text = re.sub(r"\(\s*1\s*\)\s*[^.\n:]*[:.]?\s*.*?(?:\n|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*2\s*\)\s*[^.\n:]*[:.]?\s*.*?(?:\n|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*3\s*\)\s*[^.\n:]*[:.]?\s*", "Batafsil: ", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*4\s*\)\s*[^.\n:]*[:.]?\s*", "\nQisqa qilib aytganda: ", text, flags=re.IGNORECASE)
    text = re.sub(r"details?\s*:", "Batafsil:", text, flags=re.IGNORECASE)
    text = re.sub(r"in\s*short\s*:", "Qisqa qilib aytganda:", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*manba\s*:\s*.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if "Batafsil:" not in text:
        text = f"Batafsil: {text}"
    if "Qisqa qilib aytganda:" not in text:
        short = re.split(r"[.!?](?:\s|$)", text.replace("Batafsil:", "").strip(), maxsplit=1)[0].strip()
        if not short:
            short = _empty_answer_text(response_language)
        text = f"{text}\nQisqa qilib aytganda: {short}."
    detailed = text.split("Qisqa qilib aytganda:", 1)[0].replace("Batafsil:", "").strip()
    short = text.split("Qisqa qilib aytganda:", 1)[1].strip()
    short = re.split(r"[\n\r]+", short, maxsplit=1)[0].strip()
    if len(short.split()) > 14:
        short = " ".join(short.split()[:12]).strip(" ,;:-") + "."
    return f"{detailed_label}: {detailed}\n{short_label}: {short}"


def _build_rag_prompt(
    question: str,
    context_items: list[RetrievalItem],
    response_language: str = "uz",
    fewshot_examples: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    chunks: list[str] = []
    for idx, item in enumerate(context_items, start=1):
        if item.kind == "clause":
            chunks.append(
                "\n".join(
                    [
                        f"Manba {idx}",
                        f"Hujjat: {item.shnq_code}",
                        f"Bob: {item.chapter or 'Nomalum bob'}",
                        f"Band: {item.clause_number or '-'}",
                        f"Matn: {(item.snippet or '')[:1200]}",
                    ]
                )
            )
        elif item.kind == "image":
            chunks.append(
                "\n".join(
                    [
                        f"Manba {idx} (Rasm)",
                        f"Hujjat: {item.shnq_code}",
                        f"Bob: {item.chapter or 'Nomalum bob'}",
                        f"Ilova: {item.appendix_number or '-'}",
                        f"Rasm URL: {item.image_url or '-'}",
                        f"Matn: {(item.snippet or '')[:1200]}",
                    ]
                )
            )
        else:
            chunks.append(
                "\n".join(
                    [
                        f"Manba {idx} (Jadval satri)",
                        f"Hujjat: {item.shnq_code}",
                        f"Bo'lim: {item.chapter or 'Nomalum bob'}",
                        f"Jadval: {item.table_number or '-'}",
                        f"Satr: {item.row_index if item.row_index is not None else '-'}",
                        f"Matn: {(item.snippet or '')[:1200]}",
                    ]
                )
            )
    context = "\n\n".join(chunks) if chunks else "Mos kontekst topilmadi."
    fewshot_block = ""
    if fewshot_examples:
        parts = [f"Namuna {i}\nSavol: {x['question']}\nJavob: {x['answer']}" for i, x in enumerate(fewshot_examples, start=1)]
        fewshot_block = "\n\nJavob uslubi namunalari:\n" + "\n\n".join(parts)
    detailed_label, short_label = _answer_labels(response_language)
    doc_list_instruction = ""
    if _is_document_list_request(question):
        doc_list_instruction = " Agar savolda qaysi SHNQ/hujjat so'ralgan bo'lsa, kontekstdagi SHNQ kodlarini to'liq ro'yxat qilib bering."
    system = (
        "Siz SHNQ AI'siz. Faqat SHNQ/QMQ va qurilish normalari hujjatlariga tayangan holda javob bering. "
        "Hech qachon norma o'ylab topmang. Kontekstda javob bo'lmasa, buni ochiq ayting. "
        f"Javobda faqat ikki qism bo'lsin: batafsil va qisqa xulosa.{doc_list_instruction}"
    )
    prompt = (
        f"Savol: {question}\n\nKontekst:\n{context}{fewshot_block}\n\n"
        f"Format:\n{detailed_label}:\n{short_label}:\n\nJavob:"
    )
    return system, prompt


def _merge_retrieval_candidates(primary: list[RetrievalItem], secondary: list[RetrievalItem], secondary_weight: float = 1.0) -> list[RetrievalItem]:
    merged: dict[str, RetrievalItem] = {}
    for item in primary:
        key = f"{item.kind}:{item.clause_id or item.table_id or item.image_id or item.title}"
        merged[key] = copy.deepcopy(item)
    for item in secondary:
        candidate = copy.deepcopy(item)
        candidate.score = candidate.score * secondary_weight
        key = f"{candidate.kind}:{candidate.clause_id or candidate.table_id or candidate.image_id or candidate.title}"
        prev = merged.get(key)
        if prev is None or candidate.score > prev.score:
            merged[key] = candidate
    out = list(merged.values())
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def _should_ask_document_clarification(items: list[RetrievalItem], best_score: float) -> tuple[bool, list[str]]:
    if len(items) < 2:
        return False, []
    threshold = max(settings.RAG_LOW_CONFIDENCE_FLOOR, best_score - settings.RAG_AMBIGUITY_SCORE_GAP)
    docs: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.score < threshold:
            break
        code = (item.shnq_code or "").strip()
        key = code.lower()
        if not code or key in seen:
            continue
        seen.add(key)
        docs.append(code)
        if len(docs) >= settings.RAG_AMBIGUITY_MAX_DOCS:
            break
    if len(docs) <= 1:
        return False, docs
    second_score = items[1].score
    close_scores = (best_score - second_score) <= settings.RAG_AMBIGUITY_SCORE_GAP
    low_confidence = best_score < settings.RAG_STRICT_MIN_SCORE
    return close_scores or low_confidence, docs


def _can_answer_with_relaxed_threshold(items: list[RetrievalItem], best_score: float) -> bool:
    if not items:
        return False
    if best_score >= settings.RAG_STRICT_MIN_SCORE:
        return True
    if best_score < max(settings.RAG_MIN_SCORE, settings.RAG_STRICT_MIN_SCORE - settings.RAG_NEAR_STRICT_MARGIN):
        return False
    window = items[: max(1, settings.RAG_DOMINANCE_WINDOW)]
    top_doc = window[0].shnq_code
    if not top_doc:
        return False
    ratio = sum(1 for item in window if item.shnq_code == top_doc) / max(len(window), 1)
    top_keyword = window[0].keyword_score or 0.0
    return ratio >= settings.RAG_DOC_DOMINANCE_MIN_RATIO and top_keyword >= settings.RAG_STRONG_KEYWORD_MIN


def _get_document_titles_by_code(db: Session, docs: list[str]) -> dict[str, str]:
    normalized_docs = [code.strip() for code in docs if code and code.strip()]
    if not normalized_docs:
        return {}

    rows = db.query(Document.code, Document.title).filter(Document.code.in_(normalized_docs)).all()
    title_by_code: dict[str, str] = {}
    for row in rows:
        code = (row.code or "").strip()
        title = " ".join((row.title or "").split())
        if not code or not title:
            continue
        key = code.lower()
        if key not in title_by_code:
            title_by_code[key] = title
    return title_by_code


def _build_document_clarification_answer(docs: list[str], title_by_code: dict[str, str] | None = None) -> str:
    return (
        "Shu SHNQ hujjatlarida siz so'ragan savolga mos javob bor. "
        "Aynan qaysi SHNQ nazarda tutilyapti?\n"
        + _format_document_options(docs, title_by_code)
    )


def _build_table_document_clarification_answer(
    table_number: str,
    docs: list[str],
    title_by_code: dict[str, str] | None = None,
) -> str:
    if not docs:
        return f"{table_number}-jadval qaysi hujjatda kerak? (masalan: SHNQ 2.07.01-23)"
    return (
        f"{table_number}-jadval quyidagi SHNQ hujjatlarida uchraydi. "
        "Aynan qaysi SHNQ nazarda tutilyapti?\n"
        + _format_document_options(docs, title_by_code)
    )


def _extract_image_url_from_text(text: str) -> str | None:
    match = IMAGE_URL_RE.search(text or "")
    if not match:
        return None
    return match.group(1).rstrip(").,;")


def _hydrate_clause_items(db: Session, items: list[RetrievalItem]) -> None:
    ids = [item.clause_id for item in items if item.kind == "clause" and item.clause_id]
    if not ids:
        return
    rows = (
        db.query(Clause)
        .options(joinedload(Clause.document), joinedload(Clause.chapter))
        .filter(Clause.id.in_(ids))
        .all()
    )
    row_map = {str(row.id): row for row in rows}
    for item in items:
        if item.kind != "clause" or not item.clause_id:
            continue
        row = row_map.get(item.clause_id)
        if not row:
            continue
        item.clause_number = row.clause_number
        item.html_anchor = row.html_anchor
        item.chapter = row.chapter.title if row.chapter else item.chapter
        if row.document:
            item.shnq_code = row.document.code
            item.lex_url = row.document.lex_url
        item.title = f"Band {row.clause_number or '-'}"
        item.snippet = (row.text or "")[:900]


def _source_from_item(item: RetrievalItem) -> dict[str, object]:
    if item.kind == "clause":
        return {
            "type": "clause",
            "shnq_code": item.shnq_code,
            "chapter": item.chapter,
            "clause_number": item.clause_number,
            "html_anchor": item.html_anchor,
            "lex_url": item.lex_url,
            "snippet": (item.snippet or "")[:280],
            "score": round(item.score, 4),
            "semantic_score": round(item.semantic_score or 0.0, 4),
            "keyword_score": round(item.keyword_score or 0.0, 4),
        }
    if item.kind == "image":
        return {
            "type": "image",
            "shnq_code": item.shnq_code,
            "chapter": item.chapter,
            "appendix_number": item.appendix_number,
            "title": item.title,
            "html_anchor": item.html_anchor,
            "image_url": item.image_url or _extract_image_url_from_text(item.snippet),
            "snippet": (item.snippet or "")[:280],
            "score": round(item.score, 4),
            "semantic_score": round(item.semantic_score or 0.0, 4),
            "keyword_score": round(item.keyword_score or 0.0, 4),
        }
    return {
        "type": "table_row",
        "shnq_code": item.shnq_code,
        "chapter": item.chapter,
        "table_number": item.table_number,
        "title": item.title,
        "row_index": item.row_index,
        "snippet": (item.snippet or "")[:320],
        "score": round(item.score, 4),
        "semantic_score": round(item.semantic_score or 0.0, 4),
        "keyword_score": round(item.keyword_score or 0.0, 4),
    }


def _get_pretranslated_table_content(table: NormTable, language: str) -> tuple[str, str]:
    target = (language or "uz").lower()
    if target == "en" and ((table.raw_html_en or "").strip() or (table.markdown_en or "").strip()):
        return table.raw_html_en or table.raw_html or "", table.markdown_en or table.markdown or ""
    if target == "ru" and ((table.raw_html_ru or "").strip() or (table.markdown_ru or "").strip()):
        return table.raw_html_ru or table.raw_html or "", table.markdown_ru or table.markdown or ""
    if target == "ko" and ((table.raw_html_ko or "").strip() or (table.markdown_ko or "").strip()):
        return table.raw_html_ko or table.raw_html or "", table.markdown_ko or table.markdown or ""
    return table.raw_html or "", table.markdown or ""


def _has_pretranslated_table_content(table: NormTable | None, language: str) -> bool:
    if not table:
        return False
    target = (language or "uz").lower()
    if target == "en":
        return bool((table.raw_html_en or "").strip() or (table.markdown_en or "").strip())
    if target == "ru":
        return bool((table.raw_html_ru or "").strip() or (table.markdown_ru or "").strip())
    if target == "ko":
        return bool((table.raw_html_ko or "").strip() or (table.markdown_ko or "").strip())
    return False


def _attach_timing_meta(meta: dict[str, object], timings: dict[str, float], started_at: float) -> None:
    order = ["detect", "translate_in", "embed", "rag_generate", "translate_out"]
    ms = {k: round(float(timings.get(k, 0.0)), 2) for k in order}
    active = {k: v for k, v in ms.items() if v > 0}
    if active:
        slowest = max(active, key=active.get)
        meta["timings_ms"] = ms
        meta["slowest_stage"] = slowest
        meta["slowest_stage_ms"] = active[slowest]
    meta["total_ms"] = round((time.perf_counter() - started_at) * 1000, 2)


def _build_table_qa_answer(question: str, table: NormTable, response_language: str) -> str:
    detailed_label, short_label = _answer_labels(response_language)
    context = (table.markdown or table.raw_html or "")[:6000]
    if not context.strip():
        return f"{detailed_label}: Jadval topildi, lekin matn kontenti bo'sh.\n{short_label}: Jadval kontenti mavjud emas."
    prompt = (
        f"Savol: {question}\n\n"
        f"Hujjat: {table.document.code if table.document else '-'}\n"
        f"Bo'lim: {table.section_title or (table.chapter.title if table.chapter else '-')}\n"
        f"Jadval raqami: {table.table_number}\n"
        f"Jadval sarlavhasi: {table.title or '-'}\n\n"
        f"Jadval konteksti:\n{context}\n\n"
        "Format:\nBatafsil:\nQisqa qilib aytganda:\n\nJavob:"
    )
    system = (
        "Siz SHNQ jadval ekspertisiz. Faqat berilgan jadval kontekstidan javob bering. "
        "Agar aniq qiymat bo'lsa, satr/ustun mantiqini qisqa tushuntiring."
    )
    try:
        answer = generate_text(
            prompt=prompt,
            system=system,
            model=settings.CHAT_MODEL,
            options={"temperature": 0.0, "top_p": 0.9, "max_tokens": min(settings.RAG_FINAL_MAX_TOKENS, 260)},
        )
        return _cleanup_answer_format(answer, response_language=response_language)
    except Exception:
        preview = (table.markdown or "").strip()[:220]
        if not preview:
            preview = "Jadval ma'lumotlari mavjud, ammo LLM javobi olinmadi."
        return f"{detailed_label}: {preview}\n{short_label}: {preview[:140]}"


def _select_context_items(query: str, items: list[RetrievalItem]) -> list[RetrievalItem]:
    if not items:
        return []
    if not _is_table_row_priority_query(query):
        return items[:6]

    row_items = [item for item in items if item.kind == "table_row"]
    other_items = [item for item in items if item.kind != "table_row"]
    if not row_items:
        return items[:6]

    selected = [*row_items[:4], *other_items[:3]]
    selected.sort(key=lambda x: x.score, reverse=True)
    return selected[:6]


def answer_message(db: Session, message: str, document_code: str | None = None) -> dict:
    started_at = time.perf_counter()
    timings = {"detect": 0.0, "translate_in": 0.0, "embed": 0.0, "rag_generate": 0.0, "translate_out": 0.0}

    original_message = (message or "").strip()
    if not original_message:
        raise ValueError("message is required")

    detected_language = "uz"
    search_message = original_message
    try:
        t_detect = time.perf_counter()
        detected_language = detect_query_language(original_message)
        timings["detect"] = round((time.perf_counter() - t_detect) * 1000, 2)
        if detected_language in {"en", "ru", "ko"}:
            t_translate = time.perf_counter()
            search_message = translate_query_for_search(original_message, detected_language)
            timings["translate_in"] = round((time.perf_counter() - t_translate) * 1000, 2)
    except Exception:
        detected_language = "uz"
        search_message = original_message

    if _is_greeting(search_message):
        meta = {"type": "greeting", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": _build_greeting_response(), "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    if _is_clearly_out_of_scope(search_message) and not _is_shnq_related(search_message):
        meta = {"type": "out_of_scope", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": _build_out_of_scope_response(), "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    requested_doc_code = document_code or _extract_doc_code(original_message) or _extract_doc_code(search_message)

    if _is_table_request(search_message):
        table, table_number, doc_code, candidates = _find_table_for_query(db, search_message, requested_doc_code)
        if not table_number:
            meta = {"type": "clarification", "missing_case": "missing_table_number", "model": settings.CHAT_MODEL, "query_language": detected_language}
            _attach_timing_meta(meta, timings, started_at)
            return {"answer": "Qaysi jadval nazarda tutilmoqda? (masalan: 9-jadval)", "sources": [], "table_html": None, "image_urls": [], "meta": meta}
        if not doc_code:
            docs = _table_candidate_docs(db, table_number)
            if len(docs) == 1 and table:
                doc_code = docs[0]
            else:
                title_by_code = _get_document_titles_by_code(db, docs)
                meta = {
                    "type": "clarification",
                    "missing_case": "missing_document_for_table",
                    "model": settings.CHAT_MODEL,
                    "candidate_documents": docs,
                    "query_language": detected_language,
                }
                _attach_timing_meta(meta, timings, started_at)
                return {
                    "answer": _build_table_document_clarification_answer(table_number, docs, title_by_code),
                    "sources": [],
                    "table_html": None,
                    "image_urls": [],
                    "meta": meta,
                }
        if not table and candidates:
            chapters = _table_candidate_chapters(candidates)
            chapter_hint = f" Variantlar: {', '.join(chapters)}." if chapters else ""
            meta = {
                "type": "clarification",
                "missing_case": "missing_table_chapter_context",
                "model": settings.CHAT_MODEL,
                "candidate_chapters": chapters,
                "query_language": detected_language,
            }
            _attach_timing_meta(meta, timings, started_at)
            return {
                "answer": f"{table_number}-jadval qaysi bo'lim/bob bo'yicha kerak?{chapter_hint}",
                "sources": [],
                "table_html": None,
                "image_urls": [],
                "meta": meta,
            }
        if not table:
            doc_label = doc_code or "ko'rsatilgan hujjat"
            meta = {"type": "no_match", "target": "table", "model": settings.CHAT_MODEL, "query_language": detected_language}
            _attach_timing_meta(meta, timings, started_at)
            return {"answer": f"{doc_label} bo'yicha {table_number}-jadval topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

        if _is_table_direct_lookup_request(search_message):
            answer = _build_table_answer(table)
        else:
            t_rag = time.perf_counter()
            answer = _build_table_qa_answer(search_message, table, detected_language)
            timings["rag_generate"] = round((time.perf_counter() - t_rag) * 1000, 2)
        t_out = time.perf_counter()
        answer = ensure_answer_language(answer, detected_language)
        timings["translate_out"] = round((time.perf_counter() - t_out) * 1000, 2)

        table_html, table_md = _get_pretranslated_table_content(table, detected_language)
        source = {
            "type": "table",
            "shnq_code": table.document.code if table.document else "",
            "chapter": table.section_title or (table.chapter.title if table.chapter else None),
            "table_number": table.table_number,
            "title": table.title,
            "html_anchor": table.html_anchor,
            "markdown": table_md,
            "html": table_html,
        }
        db.add(QuestionAnswer(question=original_message, answer=answer, top_clause_ids=[]))
        db.commit()
        meta = {
            "type": "table_lookup",
            "model": settings.CHAT_MODEL,
            "query_language": detected_language,
            "table_prelocalized": _has_pretranslated_table_content(table, detected_language),
        }
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": answer, "sources": [source], "table_html": table_html, "image_urls": [], "meta": meta}

    non_uz_query = detected_language in {"en", "ru", "ko"}
    translated_search_message = search_message if non_uz_query else None
    primary_query_message = original_message if (non_uz_query and settings.RAG_MULTILINGUAL_NATIVE_FIRST) else search_message
    secondary_query_message = (
        translated_search_message if (non_uz_query and settings.RAG_MULTILINGUAL_TRANSLATE_FALLBACK) else None
    )
    rewritten_primary = _rewrite_query_if_needed(primary_query_message)
    rewritten_secondary: str | None = None
    translation_fallback_used = False

    def compute_candidates(query_text: str) -> tuple[list[RetrievalItem], list[RetrievalItem], list[RetrievalItem]]:
        t_embed = time.perf_counter()
        query_vec = embed_text(query_text)
        timings["embed"] = round(timings["embed"] + ((time.perf_counter() - t_embed) * 1000), 2)
        clause_items = _search_clause_candidates(db, query_text, query_vec, requested_doc_code)
        if not clause_items:
            raw_q = db.query(Clause).options(joinedload(Clause.document))
            if requested_doc_code:
                raw_q = raw_q.filter(Clause.document.has(code=requested_doc_code))
            raw_rows = raw_q.order_by(Clause.order).limit(4000).all()
            words = [w.lower() for w in query_text.split() if len(w) > 2]
            keyword_hits: list[RetrievalItem] = []
            for row in raw_rows:
                text_l = (row.text or "").lower()
                hit = sum(1 for w in words if w in text_l)
                if hit <= 0:
                    continue
                keyword_hits.append(
                    RetrievalItem(
                        kind="clause",
                        score=float(hit),
                        title=f"Band {row.clause_number or '-'}",
                        snippet=(row.text or "")[:900],
                        shnq_code=row.document.code if row.document else "",
                        clause_id=str(row.id),
                        clause_number=row.clause_number,
                        html_anchor=row.html_anchor,
                        chapter=row.chapter.title if row.chapter else None,
                        lex_url=row.document.lex_url if row.document else None,
                        semantic_score=0.0,
                        keyword_score=float(hit),
                    )
                )
            keyword_hits.sort(key=lambda x: x.score, reverse=True)
            clause_items = keyword_hits[: settings.RAG_TOP_K]

        clause_best_score = clause_items[0].score if clause_items else 0.0
        hint = any(h in _normalize_text(query_text) for h in ["jadval", "table", "satr", "ilova", "appendix", "rasm", "image", "diagramma", "sxema"])
        row_priority = _is_table_row_priority_query(query_text)
        need_rich_sources = hint or row_priority or clause_best_score < 0.55
        row_items = _search_table_row_candidates(
            db,
            query_text,
            query_vec,
            requested_doc_code,
            row_priority=row_priority,
        ) if need_rich_sources else []
        if need_rich_sources and (row_priority or not row_items):
            row_fallback = _search_table_row_keyword_fallback(
                db,
                query_text,
                requested_doc_code,
                limit=max(settings.RAG_TABLE_ROW_TOP_K, 8),
            )
            if row_fallback:
                row_items = _merge_retrieval_candidates(row_items, row_fallback, secondary_weight=1.05)
        image_items = _search_image_candidates(db, query_text, query_vec, requested_doc_code) if need_rich_sources else []
        return clause_items, row_items, image_items

    clause_items, row_items, image_items = compute_candidates(rewritten_primary)
    primary_best_score = clause_items[0].score if clause_items else 0.0
    can_try_translated_fallback = (
        secondary_query_message
        and secondary_query_message.strip()
        and secondary_query_message.strip().lower() != primary_query_message.strip().lower()
    )
    if can_try_translated_fallback and ((not clause_items) or primary_best_score < settings.RAG_TRANSLATION_FALLBACK_THRESHOLD):
        rewritten_secondary = _rewrite_query_if_needed(secondary_query_message)
        sec_clause, sec_rows, sec_images = compute_candidates(rewritten_secondary)
        if sec_clause:
            clause_items = _merge_retrieval_candidates(clause_items, sec_clause, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)
            translation_fallback_used = True
        if sec_rows:
            row_items = _merge_retrieval_candidates(row_items, sec_rows, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)
        if sec_images:
            image_items = _merge_retrieval_candidates(image_items, sec_images, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)

    if requested_doc_code and not clause_items and not image_items and not row_items:
        meta = {"type": "no_match", "target": "document", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": f"{requested_doc_code} bo'yicha mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    best_score = clause_items[0].score if clause_items else 0.0
    if not requested_doc_code:
        ask_doc, docs = _should_ask_document_clarification(clause_items, best_score)
        if ask_doc:
            title_by_code = _get_document_titles_by_code(db, docs)
            meta = {
                "type": "clarification",
                "missing_case": "ambiguous_document",
                "candidate_documents": docs,
                "model": settings.CHAT_MODEL,
                "query_language": detected_language,
            }
            _attach_timing_meta(meta, timings, started_at)
            return {
                "answer": _build_document_clarification_answer(docs, title_by_code),
                "sources": [],
                "table_html": None,
                "image_urls": [],
                "meta": meta,
            }

    relaxed = _can_answer_with_relaxed_threshold(clause_items, best_score)
    if best_score < settings.RAG_STRICT_MIN_SCORE and not (relaxed or row_items or image_items):
        clarification = _needs_clarification(search_message)
        if clarification:
            code, question = clarification
            meta = {"type": "clarification", "missing_case": code, "model": settings.CHAT_MODEL, "query_language": detected_language}
            _attach_timing_meta(meta, timings, started_at)
            return {"answer": question, "sources": [], "table_html": None, "image_urls": [], "meta": meta}
        meta = {"type": "no_match", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": "Mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    merged_all = sorted([*clause_items, *row_items, *image_items], key=lambda x: x.score, reverse=True)[: settings.RAG_FINAL_K]
    merged = _select_context_items(original_message, merged_all)
    _hydrate_clause_items(db, merged)
    if not merged:
        meta = {"type": "no_match", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": "Mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    fewshot_examples = _pick_fewshot_examples(original_message, limit=3)
    system, prompt = _build_rag_prompt(original_message, merged, response_language=detected_language, fewshot_examples=fewshot_examples)
    llm_used = False
    llm_error: str | None = None
    llm_error_detail: str | None = None
    try:
        t_rag = time.perf_counter()
        answer = generate_text(
            prompt=prompt,
            system=system,
            model=settings.CHAT_MODEL,
            options={"temperature": 0.0, "top_p": 0.9, "max_tokens": settings.RAG_FINAL_MAX_TOKENS},
        )
        timings["rag_generate"] = round((time.perf_counter() - t_rag) * 1000, 2)
        llm_used = True
    except Exception as exc:
        llm_error = "primary_generate_failed"
        llm_error_detail = f"{type(exc).__name__}: {str(exc)[:220]}"
        try:
            answer = generate_answer(original_message, context="\n\n".join(i.snippet for i in merged), model=settings.CHAT_MODEL)
            llm_used = True
        except Exception as fallback_exc:
            llm_error = "llm_unavailable_fallback_used"
            llm_error_detail = f"{type(fallback_exc).__name__}: {str(fallback_exc)[:220]}"
            answer = merged[0].snippet if merged else _empty_answer_text(detected_language)

    if not answer:
        answer = merged[0].snippet if merged else _empty_answer_text(detected_language)

    # "Qaysi SHNQ?" turidagi savollarda model kodlarni chiqarolmasa,
    # kontekstdan topilgan hujjat kodlari bilan deterministic fallback beramiz.
    if _is_document_list_request(search_message):
        context_codes = _collect_codes_from_items(merged)
        answer_codes = _extract_document_codes(answer or "")
        if context_codes and not answer_codes:
            title_by_code = _get_document_titles_by_code(db, context_codes)
            answer = _build_document_list_answer(context_codes, detected_language, title_by_code)

    answer = _cleanup_answer_format(answer, response_language=detected_language)
    t_out = time.perf_counter()
    answer = ensure_answer_language(answer, detected_language)
    timings["translate_out"] = round((time.perf_counter() - t_out) * 1000, 2)

    top_clause_ids = [item.clause_id for item in clause_items[:5] if item.clause_id]
    db.add(QuestionAnswer(question=original_message, answer=answer, top_clause_ids=top_clause_ids))
    db.commit()

    sources = [_source_from_item(item) for item in merged]
    related_table: NormTable | None = None
    for item in merged_all:
        if item.kind == "table_row" and item.table_id:
            related_table = db.query(NormTable).options(joinedload(NormTable.document), joinedload(NormTable.chapter)).filter(NormTable.id == item.table_id).first()
            if related_table:
                break

    table_html = None
    if related_table:
        table_html, table_md = _get_pretranslated_table_content(related_table, detected_language)
        sources.append(
            {
                "type": "table",
                "shnq_code": related_table.document.code if related_table.document else "",
                "chapter": related_table.section_title or (related_table.chapter.title if related_table.chapter else None),
                "table_number": related_table.table_number,
                "title": related_table.title,
                "html_anchor": related_table.html_anchor,
                "markdown": table_md,
                "html": table_html,
            }
        )

    image_urls: list[str] = []
    seen_image_urls: set[str] = set()
    for src in sources:
        if not isinstance(src, dict):
            continue
        url = src.get("image_url")
        if not url and isinstance(src.get("snippet"), str):
            url = _extract_image_url_from_text(src["snippet"])
            if url:
                src["image_url"] = url
        if not url or url in seen_image_urls:
            continue
        seen_image_urls.add(url)
        image_urls.append(url)

    rewritten_any = (rewritten_primary != primary_query_message) or (
        rewritten_secondary is not None and secondary_query_message is not None and rewritten_secondary != secondary_query_message
    )
    meta = {
        "type": "rag",
        "model": settings.CHAT_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "answer_language": detected_language,
        "query_language": detected_language,
        "min_score": settings.RAG_MIN_SCORE,
        "strict_min_score": settings.RAG_STRICT_MIN_SCORE,
        "relaxed_threshold_used": best_score < settings.RAG_STRICT_MIN_SCORE and relaxed,
        "keyword_weight": settings.RAG_KEYWORD_WEIGHT,
        "rerank_enabled": settings.RAG_ENABLE_RERANK,
        "rerank_candidates": settings.RAG_RERANK_CANDIDATES,
        "rewritten": rewritten_any,
        "query_used": rewritten_primary,
        "query_used_fallback": rewritten_secondary,
        "query_original": original_message,
        "requested_document": requested_doc_code,
        "multilingual_native_first": settings.RAG_MULTILINGUAL_NATIVE_FIRST,
        "translation_fallback_used": translation_fallback_used,
        "translation_fallback_threshold": settings.RAG_TRANSLATION_FALLBACK_THRESHOLD,
        "translated_query_score_weight": settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT,
        "fewshot_examples_used": len(fewshot_examples),
        "image_sources": len([i for i in merged if i.kind == "image"]),
        "table_row_sources": len([i for i in merged if i.kind == "table_row"]),
        "table_prelocalized": _has_pretranslated_table_content(related_table, detected_language),
        "best_score": round(best_score, 4),
        "qdrant_enabled": settings.RAG_USE_QDRANT,
        "llm_used": llm_used,
        "llm_error": llm_error,
        "llm_error_detail": llm_error_detail,
    }
    _attach_timing_meta(meta, timings, started_at)

    return {"answer": answer, "sources": sources, "table_html": table_html, "image_urls": image_urls, "meta": meta}
