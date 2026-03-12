from __future__ import annotations

import copy
import json
import logging
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
from app.rag.confidence import assess_confidence
from app.rag.document_router import route_documents
from app.rag.hybrid_search import reciprocal_rank_fusion
from app.rag.metadata_filter import MetadataFilters, match_item_filters
from app.rag.query_intent import IntentResult, classify_query_intent
from app.rag.reference_parser import ExactReference, extract_document_codes, parse_exact_references
from app.rag.re_ranker import rerank_clauses
from app.rag.retriever import retrieve_db_dense_fallback, retrieve_dense_clauses, retrieve_lexical_clauses
from app.rag.unified_reranker import rerank_mixed_items
from app.utils.text_fix import repair_mojibake, to_cp1251_mojibake
from app.services.llm_service import (
    detect_query_language,
    embed_text,
    ensure_answer_language,
    generate_answer,
    generate_text,
    translate_query_for_search,
)

logger = logging.getLogger(__name__)

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
CLAUSE_LOOKUP_RE = re.compile(
    r"(?:\b\d+\s*[-.]?\s*band(?:da|ni|ga|dan|ning|lar)?\b|\bband(?:da|ni|ga|dan|ning|lar)?\b|\bmodda\b)",
    re.IGNORECASE,
)
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
NUMERIC_REQUIREMENT_HINTS = {
    "minimal",
    "maksimal",
    "kamida",
    "ko'pi",
    "masofa",
    "foiz",
    "ulush",
    "norma",
    "me'yor",
    "meyor",
    "qancha",
    "necha",
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
SPECIFICITY_STOPWORDS = {
    "minimal",
    "maksimal",
    "kamida",
    "ko'pi",
    "foiz",
    "ulush",
    "qancha",
    "necha",
    "kerak",
    "talab",
    "norma",
    "me'yor",
    "meyor",
    "hujjat",
    "band",
    "bob",
}
TABLE_CONTEXT_STOP_WORDS = {
    "jadval",
    "jadvlda",
    "jadvl",
    "jdval",
    "table",
    "ilova",
    "appendix",
    "haqida",
    "malumot",
    "ma'lumot",
    "nima",
    "deyilgan",
    "ber",
    "bering",
    "korsat",
    "ko'rsat",
    "qaysi",
    "boyicha",
    "bo'yicha",
    "shnq",
    "qmq",
    "kmk",
    "snip",
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
    document_id: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    page: str | None = None
    language: str | None = "uz"
    content_type: str | None = None
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
    repaired = repair_mojibake(text or "")
    lowered = unicodedata.normalize("NFKC", repaired).strip().lower()
    lowered = lowered.translate(APOSTROPHE_VARIANTS)
    return re.sub(r"\s+", " ", lowered)


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _log_debug(event: str, **kwargs: object) -> None:
    if not settings.RAG_DEBUG_LOGGING:
        return
    try:
        logger.info("[rag_debug] %s | %s", event, json.dumps(kwargs, ensure_ascii=False, default=str))
    except Exception:
        logger.info("[rag_debug] %s | %s", event, kwargs)


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
    codes = extract_document_codes(_normalize_text(text))
    if not codes:
        return None
    return codes[0]


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


def _table_reference_regex(table_number: str) -> re.Pattern[str]:
    normalized = _normalize_table_reference(table_number)
    escaped = re.escape(normalized).replace(r"\.", r"[\s,.\-]*")
    pattern = (
        rf"(?:\bjadval(?:da|ni|ga|dan|ning|lar)?\s*[-.]?\s*{escaped}\b|"
        rf"\b{escaped}\s*[-.]?\s*jadval(?:da|ni|ga|dan|ning|lar)?\b)"
    )
    return re.compile(pattern, re.IGNORECASE)


def _table_reference_in_text(text: str | None, table_number: str) -> bool:
    value = _normalize_text(text or "")
    if not value:
        return False
    return bool(_table_reference_regex(table_number).search(value))


def _table_query_terms(message: str) -> list[str]:
    terms = _extract_query_terms(message)
    generic = {"jadval", "table", "satr", "ustun", "ilova", "appendix"}
    return [term for term in terms if term not in generic]


def _normalize_doc_code(text: str | None) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def _extract_table_context_terms(message: str, doc_code: str | None, table_number: str | None) -> list[str]:
    normalized = _normalize_text(message)
    terms = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", normalized, flags=re.UNICODE)
    doc_terms = set(re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", _normalize_text(doc_code or ""), flags=re.UNICODE))
    number = (table_number or "").lower()
    cleaned: list[str] = []
    for term in terms:
        if len(term) < 3:
            continue
        if term in TABLE_CONTEXT_STOP_WORDS:
            continue
        if term in doc_terms:
            continue
        if number and term == number:
            continue
        cleaned.append(term)
    uniq: list[str] = []
    seen: set[str] = set()
    for term in cleaned:
        if term in seen:
            continue
        seen.add(term)
        uniq.append(term)
    return uniq


def _table_exact_section_hit(table: NormTable, normalized_message: str) -> bool:
    section = _normalize_text(table.section_title or "")
    if len(section) < 8:
        return False
    if section in normalized_message:
        return True
    section_core = re.sub(r"^\d+\s*[-.]?\s*(?:§|bob)?\.?\s*", "", section).strip()
    return len(section_core) >= 8 and section_core in normalized_message


def _table_context_score(table: NormTable, context_terms: list[str]) -> int:
    if not context_terms:
        return 0
    haystack = _normalize_text(
        f"{table.document.code if table.document else ''} "
        f"{table.section_title or ''} "
        f"{table.chapter.title if table.chapter else ''} "
        f"{table.title or ''} "
        f"{(table.markdown or '')[:2500]} "
        f"{(table.raw_html or '')[:2500]}"
    )
    return sum(1 for term in context_terms if term in haystack)


def _score_table_candidate(message: str, table_number: str, table: NormTable) -> float:
    terms = _table_query_terms(message)
    title_text = " | ".join(
        part for part in [table.title or "", table.section_title or "", table.table_number or ""] if part
    )
    body_text = (table.markdown or table.raw_html or "")[:2000]
    combined = f"{title_text} | {body_text}"
    keyword = _keyword_score(terms, combined) if terms else 0.0
    title_keyword = _keyword_score(terms, title_text) if terms else 0.0
    number_match = 1.0 if _match_table_number(table.table_number, table_number) else 0.0
    mention_match = 1.0 if _table_reference_in_text(combined, table_number) else 0.0
    return (number_match * 0.55) + (mention_match * 0.15) + (title_keyword * 0.6) + (keyword * 0.35)


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


def _is_explicit_clause_lookup(text: str) -> bool:
    return bool(CLAUSE_LOOKUP_RE.search(text or ""))


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
    doc_key = _normalize_doc_code(doc_code)

    candidate_pool = query.filter(or_(*[NormTable.table_number.ilike(variant) for variant in variants])).all()
    candidate_pool = [item for item in candidate_pool if _match_table_number(item.table_number, table_number)]

    if not candidate_pool and table_number.startswith("ilova-"):
        appendix_number = table_number.split("-", 1)[1]
        key_variants = {f"{appendix_number}-ilova", f"{appendix_number} ilova"}
        fallback_rows = query.limit(3000).all()
        candidate_pool = [
            item
            for item in fallback_rows
            if any(
                key in _normalize_text(
                    f"{item.section_title or ''} {item.title or ''} {(item.markdown or '')[:1200]}"
                )
                for key in key_variants
            )
        ]

    if doc_key:
        candidate_pool = [
            item
            for item in candidate_pool
            if item.document and doc_key in _normalize_doc_code(item.document.code)
        ]

    unique: list[NormTable] = []
    seen_ids: set[str] = set()
    for item in candidate_pool:
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

    normalized_message = _normalize_text(message)
    context_terms = _extract_table_context_terms(message, doc_code, table_number)
    if context_terms:
        exact_matches = [item for item in candidates if _table_exact_section_hit(item, normalized_message)]
        if exact_matches:
            section_keys = {
                _normalize_text(item.section_title or (item.chapter.title if item.chapter else ""))
                for item in exact_matches
            }
            if len(section_keys) == 1:
                picked = sorted(exact_matches, key=lambda x: x.order)[0]
                return picked, table_number, doc_code, candidates

        scored = sorted(
            candidates,
            key=lambda item: (
                1 if _table_exact_section_hit(item, normalized_message) else 0,
                _score_table_candidate(message, table_number, item),
                _table_context_score(item, context_terms),
                -int(item.order or 0),
            ),
            reverse=True,
        )
        best = scored[0]
        best_exact = _table_exact_section_hit(best, normalized_message)
        second_exact = _table_exact_section_hit(scored[1], normalized_message) if len(scored) > 1 else False
        best_context_score = _table_context_score(best, context_terms)
        second_context_score = _table_context_score(scored[1], context_terms) if len(scored) > 1 else -1
        best_candidate_score = _score_table_candidate(message, table_number, best)
        second_candidate_score = _score_table_candidate(message, table_number, scored[1]) if len(scored) > 1 else -1.0

        if best_exact and not second_exact:
            return best, table_number, doc_code, candidates
        if best_context_score > 0 and best_context_score > second_context_score:
            return best, table_number, doc_code, candidates
        if best_candidate_score >= 0.75 and best_candidate_score >= (second_candidate_score + 0.08):
            return best, table_number, doc_code, candidates
        if len(scored) == 1:
            return scored[0], table_number, doc_code, candidates
        return None, table_number, doc_code, scored

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
        return False
    has_table_hint = any(term in normalized for term in ("jadval", "satr", "ustun", "table", "ilova"))
    if not has_table_hint:
        return False
    has_focus_term = any(term in normalized for term in ROW_FOCUS_TERMS)
    has_question_intent = any(word in normalized for word in ("qaysi", "qanday", "keltirilgan", "berilgan", "talab"))
    return has_focus_term and has_question_intent


def _is_table_intent_query(text: str) -> bool:
    normalized = _normalize_text(text)
    if _is_table_request(normalized):
        return True
    explicit_terms = ("jadval", "satr", "ustun", "ilova", "appendix", "table")
    return any(term in normalized for term in explicit_terms)


def _is_numeric_requirement_query(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(token in normalized for token in NUMERIC_REQUIREMENT_HINTS)


def _extract_document_codes(text: str) -> list[str]:
    return extract_document_codes(_normalize_text(text))


def _is_document_list_request(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(phrase in normalized for phrase in ("qaysi shnq", "qaysi hujjat", "qaysi norma", "qaysi normativ"))


def _build_metadata_filters(
    intent: IntentResult,
    reference: ExactReference,
    selected_doc_codes: list[str] | None = None,
) -> MetadataFilters:
    filters = MetadataFilters(
        document_codes=[*reference.document_codes, *(selected_doc_codes or [])],
        clause_numbers=reference.clause_numbers[:],
        table_numbers=reference.table_numbers[:],
        appendix_numbers=reference.appendix_numbers[:],
        section_titles=[f"bob {n}" for n in reference.chapter_numbers] + [f"{n}-bob" for n in reference.chapter_numbers],
    )
    if intent.intent == "table_lookup":
        filters.content_types = ["table_row"]
    elif intent.intent == "image_lookup":
        filters.content_types = ["image"]
    elif intent.intent == "exact_band_reference":
        filters.content_types = ["clause"]
    return filters.normalized()


def _search_exact_clause_references(
    db: Session,
    reference: ExactReference,
    document_codes: list[str] | None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievalItem]:
    clause_numbers = [x.strip() for x in reference.clause_numbers if x and x.strip()]
    if not clause_numbers:
        return []

    query = db.query(Clause).options(joinedload(Clause.document), joinedload(Clause.chapter))
    if document_codes:
        query = query.filter(Clause.document.has(code=document_codes[0])) if len(document_codes) == 1 else query.filter(Clause.document.has(Document.code.in_(document_codes)))
    rows = query.filter(Clause.clause_number.in_(clause_numbers)).limit(24).all()
    out: list[RetrievalItem] = []
    for row in rows:
        item = RetrievalItem(
            kind="clause",
            score=1.35,
            title=f"Band {row.clause_number or '-'}",
            snippet=(row.text or "")[:900],
            shnq_code=row.document.code if row.document else "",
            document_id=str(row.document_id) if row.document_id else None,
            section_id=str(row.chapter_id) if row.chapter_id else None,
            section_title=row.chapter.title if row.chapter else None,
            content_type="clause",
            clause_id=str(row.id),
            clause_number=row.clause_number,
            html_anchor=row.html_anchor,
            chapter=row.chapter.title if row.chapter else None,
            lex_url=row.document.lex_url if row.document else None,
            semantic_score=1.0,
            keyword_score=1.0,
        )
        if match_item_filters(item, metadata_filters):
            out.append(item)
    out.sort(key=lambda x: x.score, reverse=True)
    return out[:6]


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


def _query_specific_terms(text: str) -> list[str]:
    terms = _extract_query_terms(text)
    specific = [
        term
        for term in terms
        if len(term) >= 7 and term not in SPECIFICITY_STOPWORDS
    ]
    if specific:
        return specific[:4]
    # fallback: if no long terms, still keep 1-2 less-generic terms
    secondary = [term for term in terms if term not in SPECIFICITY_STOPWORDS]
    return secondary[:2]


def _keyword_score(terms: list[str], text: str) -> float:
    haystack = _normalize_text(text)
    if not terms or not haystack:
        return 0.0
    return sum(1 for term in terms if term in haystack) / max(len(terms), 1)


def _clause_confidence_weight(semantic: float, keyword: float) -> float:
    quality = max(0.0, min(1.0, max(semantic, keyword)))
    # Lexical-only weak matchesni pasaytirib, aniq dense yoki keyword moslikni ustun qilamiz.
    return 0.35 + (0.65 * quality)


def _search_clause_candidates(
    db: Session,
    query: str,
    query_vec: list[float],
    doc_codes: list[str] | None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    specific_terms = _query_specific_terms(query)
    dense = retrieve_dense_clauses(
        db=db,
        query_vec=query_vec,
        document_code=None,
        document_codes=doc_codes,
        metadata_filters=metadata_filters,
        limit=settings.RAG_DENSE_K,
    )
    if not dense:
        dense = retrieve_db_dense_fallback(
            db=db,
            query_vec=query_vec,
            document_code=None,
            document_codes=doc_codes,
            metadata_filters=metadata_filters,
            limit=settings.RAG_DENSE_K,
        )
    lexical = retrieve_lexical_clauses(
        db=db,
        query=query,
        document_code=None,
        document_codes=doc_codes,
        metadata_filters=metadata_filters,
        limit=settings.RAG_LEXICAL_K,
    )
    fused = reciprocal_rank_fusion(dense, lexical, rrf_k=settings.RAG_RRF_K)
    fused = rerank_clauses(query, fused[: settings.RAG_RERANK_CANDIDATES], settings.RAG_TOP_K) if settings.RAG_ENABLE_RERANK else fused[: settings.RAG_TOP_K]
    out: list[RetrievalItem] = []
    for item in fused:
        semantic = float(item.dense_score or 0.0)
        keyword = _keyword_score(terms, item.snippet)
        specific_keyword = _keyword_score(specific_terms, item.snippet) if specific_terms else 0.0
        if specific_terms and specific_keyword <= 0 and semantic < 0.18:
            continue
        keyword = max(keyword, specific_keyword)
        if semantic < 0.02 and keyword < 0.16:
            continue
        base_score = float(item.rerank_score or item.hybrid_score or item.dense_score or item.lexical_score or 0.0)
        if base_score <= 0:
            continue
        calibrated_score = base_score * _clause_confidence_weight(semantic, keyword)
        out.append(
            RetrievalItem(
                kind="clause",
                score=calibrated_score,
                title=item.title,
                snippet=item.snippet,
                shnq_code=item.shnq_code,
                document_id=item.document_id,
                section_id=item.section_id,
                section_title=item.section_title,
                page=item.page,
                language=item.language,
                content_type=item.content_type,
                clause_id=item.clause_id,
                clause_number=item.clause_number,
                chapter=item.section_title,
                semantic_score=semantic,
                keyword_score=keyword,
            )
        )
    return [item for item in out if match_item_filters(item, metadata_filters)]


def _search_table_row_candidates(
    db: Session,
    query: str,
    query_vec: list[float],
    doc_codes: list[str] | None,
    metadata_filters: MetadataFilters | None = None,
    row_priority: bool = False,
    limit_override: int | None = None,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    specific_terms = _query_specific_terms(query)
    if not terms and not row_priority:
        return []
    normalized_query = _normalize_text(query)
    out: list[RetrievalItem] = []
    db_q = db.query(TableRowEmbedding).options(
        joinedload(TableRowEmbedding.row).joinedload(NormTableRow.table).joinedload(NormTable.document),
        joinedload(TableRowEmbedding.row).joinedload(NormTableRow.table).joinedload(NormTable.chapter),
        joinedload(TableRowEmbedding.row).joinedload(NormTableRow.cells),
    )
    if doc_codes:
        db_q = db_q.filter(TableRowEmbedding.shnq_code.in_(doc_codes))
    effective_top_k = max(1, int(limit_override or settings.RAG_TABLE_ROW_TOP_K))
    scan_limit = max(settings.RAG_TABLE_ROW_SCAN_LIMIT, effective_top_k * 60)
    if terms:
        filter_terms: list[str] = []
        for term in terms[:4]:
            if term and term not in filter_terms:
                filter_terms.append(term)
            mojibake_term = to_cp1251_mojibake(term)
            if mojibake_term and mojibake_term != term and mojibake_term not in filter_terms:
                filter_terms.append(mojibake_term)
        filters = [TableRowEmbedding.search_text.ilike(f"%{term}%") for term in filter_terms]
        candidates = db_q.filter(or_(*filters)).limit(scan_limit).all()
        if not candidates:
            # Query lexical termlari embedding search_textda topilmasa ham
            # kichik sample'da semantic tekshiruvni saqlab qolamiz.
            candidates = db_q.limit(min(400, scan_limit)).all()
    else:
        candidates = db_q.limit(min(400, scan_limit)).all()

    for emb in candidates:
        table = emb.row.table if emb.row else None
        row_cells = emb.row.cells if emb.row else []
        header_text = " | ".join(
            (cell.text or "").strip() for cell in sorted(row_cells, key=lambda x: x.col_index) if getattr(cell, "is_header", False) and (cell.text or "").strip()
        )
        row_text = " | ".join((cell.text or "").strip() for cell in sorted(row_cells, key=lambda x: x.col_index) if (cell.text or "").strip())
        combined_text = " | ".join(
            part
            for part in [
                emb.search_text or "",
                f"Header: {header_text}" if header_text else "",
                f"Row: {row_text}" if row_text else "",
                table.title if table and table.title else "",
                table.section_title if table and table.section_title else "",
            ]
            if part
        )
        normalized_row = _normalize_text(combined_text)
        semantic = _cosine(query_vec, emb.vector or [])
        keyword = _keyword_score(terms, normalized_row)
        specific_keyword = _keyword_score(specific_terms, normalized_row) if specific_terms else 0.0
        keyword = max(keyword, specific_keyword)
        tf = sum(normalized_row.count(term) for term in terms)
        coverage = sum(1 for term in terms if term in normalized_row)
        specific_coverage = sum(1 for term in specific_terms if term in normalized_row) if specific_terms else 0
        phrase_bonus = 0.35 if normalized_query and normalized_query in normalized_row else 0.0
        focus_bonus = 0.12 if row_priority and coverage >= 2 else 0.0
        score = (semantic * 0.85) + (keyword * 0.6) + min(0.35, tf * 0.06) + phrase_bonus + focus_bonus

        # Row-priority querylarda lexical moslik yetarli bo'lsa semantic past bo'lsa ham o'tkazamiz.
        if specific_terms and specific_coverage == 0 and semantic < 0.2 and not row_priority:
            continue
        if not row_priority and score < settings.RAG_TABLE_ROW_MIN_SCORE and keyword <= 0:
            continue
        if row_priority and coverage == 0 and semantic < settings.RAG_TABLE_ROW_MIN_SCORE:
            continue

        item = RetrievalItem(
            kind="table_row",
            score=score,
            title=f"Jadval {emb.table_number} / satr {emb.row_index}",
            snippet=combined_text[:900],
            shnq_code=emb.shnq_code,
            document_id=str(table.document_id) if table and table.document_id else None,
            section_id=str(table.chapter_id) if table and table.chapter_id else None,
            section_title=table.section_title if table else None,
            content_type="table_row",
            table_id=str(table.id) if table else None,
            table_number=emb.table_number,
            chapter=table.section_title if table and table.section_title else (table.chapter.title if table and table.chapter else None),
            row_index=emb.row_index,
            semantic_score=semantic,
            keyword_score=keyword,
        )
        if match_item_filters(item, metadata_filters):
            out.append(item)
    out.sort(key=lambda x: x.score, reverse=True)
    return out[: effective_top_k]


def _search_table_row_keyword_fallback(
    db: Session,
    query: str,
    doc_codes: list[str] | None,
    limit: int,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    if not terms:
        return []

    filter_terms: list[str] = []
    for term in terms[:6]:
        if term and term not in filter_terms:
            filter_terms.append(term)
        mojibake_term = to_cp1251_mojibake(term)
        if mojibake_term and mojibake_term != term and mojibake_term not in filter_terms:
            filter_terms.append(mojibake_term)
    filters = [NormTableCell.text.ilike(f"%{term}%") for term in filter_terms]
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
    if doc_codes:
        if len(doc_codes) == 1:
            db_q = db_q.filter(NormTable.document.has(code=doc_codes[0]))
        else:
            db_q = db_q.filter(NormTable.document.has(Document.code.in_(doc_codes)))

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
            document_id=str(table.document_id) if table.document_id else None,
            section_id=str(table.chapter_id) if table.chapter_id else None,
            section_title=table.section_title,
            content_type="table_row",
            table_id=str(table.id),
            table_number=table.table_number,
            chapter=table.section_title or (table.chapter.title if table.chapter else None),
            row_index=row.row_index,
            semantic_score=0.0,
            keyword_score=float(coverage / max(len(terms), 1)),
        )
        if (not prev or candidate.score > prev.score) and match_item_filters(candidate, metadata_filters):
            by_row[row_id] = candidate

    out = list(by_row.values())
    out.sort(key=lambda x: x.score, reverse=True)
    return out[: max(limit, 1)]


def _search_image_candidates(
    db: Session,
    query: str,
    query_vec: list[float],
    doc_codes: list[str] | None,
    metadata_filters: MetadataFilters | None = None,
) -> list[RetrievalItem]:
    terms = _extract_query_terms(query)
    out: list[RetrievalItem] = []
    db_q = db.query(ImageEmbedding).options(
        joinedload(ImageEmbedding.image).joinedload(NormImage.document),
        joinedload(ImageEmbedding.image).joinedload(NormImage.chapter),
    )
    if doc_codes:
        db_q = db_q.filter(ImageEmbedding.shnq_code.in_(doc_codes))
    for emb in db_q.all():
        image = emb.image
        context = " | ".join([p for p in [image.title if image else "", image.context_text if image else "", image.ocr_text if image else "", f"URL: {image.image_url}" if image else ""] if p])
        semantic = _cosine(query_vec, emb.vector or [])
        keyword = _keyword_score(terms, context)
        score = semantic + (settings.RAG_KEYWORD_WEIGHT * keyword)
        if score < settings.RAG_IMAGE_MIN_SCORE and keyword <= 0:
            continue
        item = RetrievalItem(
            kind="image",
            score=score,
            title=f"Rasm {emb.appendix_number or ''}".strip(),
            snippet=context[:900],
            shnq_code=emb.shnq_code,
            document_id=str(image.document_id) if image and image.document_id else None,
            section_id=str(image.chapter_id) if image and image.chapter_id else None,
            section_title=image.section_title if image else None,
            content_type="image",
            image_id=str(emb.image_id) if emb.image_id else None,
            chapter=emb.chapter_title,
            appendix_number=emb.appendix_number,
            html_anchor=image.html_anchor if image else None,
            image_url=image.image_url if image else emb.image_url,
            semantic_score=semantic,
            keyword_score=keyword,
        )
        if match_item_filters(item, metadata_filters):
            out.append(item)
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
    intent: IntentResult | None = None,
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
    table_instruction = ""
    compare_instruction = ""
    if _is_document_list_request(question):
        doc_list_instruction = " Agar savolda qaysi SHNQ/hujjat so'ralgan bo'lsa, kontekstdagi SHNQ kodlarini to'liq ro'yxat qilib bering."
    if _is_table_intent_query(question):
        table_instruction = (
            " Agar savol jadval/satr haqida bo'lsa, avval jadval satri kontekstiga tayangan holda javob bering, "
            "jadval raqami va satrni ko'rsating. Jadval bo'yicha aniq ma'lumot topilmasa, buni ochiq yozing."
        )
    if intent and intent.intent == "compare_documents":
        compare_instruction = " Taqqoslash savollarida har bir hujjat bo'yicha dalilni alohida ko'rsatib, farqini qisqa xulosa qiling."
    system = (
        "Siz SHNQ qurilish me'yorlari bo'yicha ekspert AI yordamchisiz.\n\n"

        "Qoidalar:\n"
        "1. Faqat berilgan kontekst asosida javob bering.\n"
        "2. Hech qachon kontekstda bo'lmagan norma yoki talabni o'ylab topmang.\n"
        "3. Agar kontekstda aniq javob bo'lmasa 'kontekstda aniq javob topilmadi' deb yozing.\n"
        "4. Javobda imkon qadar SHNQ hujjat kodi, bob va bandni ko'rsating.\n"
        "5. Agar jadval ishlatilsa jadval raqami va satrni ko'rsating.\n"
        "6. Javob texnik, aniq va ortiqcha umumiy gaplarsiz bo'lsin.\n"
        "7. Qurilish me'yorlariga zid yoki taxminiy maslahat bermang.\n"
        "8. Agar bir nechta manba bo'lsa, eng mosini tanlang va javobni aralashtirmang.\n\n"

        "Javob formati:\n"
        "Batafsil qismida norma tushuntirilsin, kerak bo'lsa raqamlar yozilsin, manba sifatida SHNQ kodi va band ko'rsatilsin.\n"
        "Qisqa qilib aytganda qismida 1-2 jumlalik xulosa yozilsin.\n\n"

        "Kontekst bir nechta 'Manba' bloklaridan iborat.\n"
        "Har bir manba alohida hujjatdan olingan.\n"
        "Eng mos manbani tanlab javob bering.\n\n"

        f"{doc_list_instruction}{table_instruction}{compare_instruction}"
    )
    prompt = (
        f"Savol: {question}\n\nKontekst:\n{context}{fewshot_block}\n\n"
        "Format:\n"
        "Batafsil:\n"
        "Qisqa qilib aytganda:\n\n"
        "Javob:"
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
    if not close_scores:
        return False, docs

    top_signal = max(float(items[0].semantic_score or 0.0), float(items[0].keyword_score or 0.0))
    second_signal = max(float(items[1].semantic_score or 0.0), float(items[1].keyword_score or 0.0))
    if top_signal < 0.22 or second_signal < 0.22:
        return False, docs

    # Past confidence holatida faqat haqiqatan bir nechta hujjatda kuchli signal bo'lsa clarification so'raymiz.
    if best_score < settings.RAG_STRICT_MIN_SCORE:
        strong_docs: set[str] = set()
        for item in items[: max(2, settings.RAG_DOMINANCE_WINDOW)]:
            if item.score < threshold:
                continue
            signal = max(float(item.semantic_score or 0.0), float(item.keyword_score or 0.0))
            code = (item.shnq_code or "").strip().lower()
            if code and signal >= max(0.24, settings.RAG_STRONG_KEYWORD_MIN * 0.8):
                strong_docs.add(code)
        if len(strong_docs) < 2:
            return False, docs

    return True, docs


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


def _is_weak_clause_only_result(
    clause_items: list[RetrievalItem],
    row_items: list[RetrievalItem],
    image_items: list[RetrievalItem],
) -> bool:
    if not clause_items or row_items or image_items:
        return False
    top = clause_items[0]
    semantic = float(top.semantic_score or 0.0)
    keyword = float(top.keyword_score or 0.0)
    return semantic < 0.02 and keyword < 0.22


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
        item.section_id = str(row.chapter_id) if row.chapter_id else item.section_id
        item.section_title = row.chapter.title if row.chapter else item.section_title
        item.document_id = str(row.document_id) if row.document_id else item.document_id
        item.content_type = item.content_type or "clause"
        item.language = item.language or "uz"
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
            "document_id": item.document_id,
            "section_id": item.section_id,
            "section_title": item.section_title,
            "page": item.page,
            "language": item.language,
            "content_type": item.content_type or "clause",
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
            "document_id": item.document_id,
            "section_id": item.section_id,
            "section_title": item.section_title,
            "page": item.page,
            "language": item.language,
            "content_type": item.content_type or "image",
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
        "document_id": item.document_id,
        "section_id": item.section_id,
        "section_title": item.section_title,
        "page": item.page,
        "language": item.language,
        "content_type": item.content_type or "table_row",
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
    table_intent = _is_table_intent_query(query)
    row_priority = _is_table_row_priority_query(query)
    if table_intent:
        row_items = [item for item in items if item.kind == "table_row"]
        other_items = [item for item in items if item.kind != "table_row"]
        if row_items:
            selected = [*row_items[:4], *other_items[:2]]
            selected.sort(key=lambda x: x.score, reverse=True)
            return selected[:6]
        return items[:6]
    if not row_priority:
        clause_items = [item for item in items if item.kind == "clause"]
        row_items = [item for item in items if item.kind == "table_row"]
        if _is_numeric_requirement_query(query) and row_items:
            top_clause = clause_items[0].score if clause_items else 0.0
            top_row = row_items[0].score
            if top_row >= (top_clause + 0.06):
                selected = [*row_items[:3], *clause_items[:3]]
                selected.sort(key=lambda x: x.score, reverse=True)
                return selected[:6]
        if clause_items:
            return clause_items[:6]
        image_items = [item for item in items if item.kind == "image"]
        if image_items:
            return image_items[:3]
        return []

    row_items = [item for item in items if item.kind == "table_row"]
    other_items = [item for item in items if item.kind != "table_row"]
    if not row_items:
        clause_items = [item for item in other_items if item.kind == "clause"]
        return clause_items[:6] if clause_items else other_items[:6]

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
    exact_reference = parse_exact_references(search_message)
    intent_result = classify_query_intent(search_message, exact_reference)
    _log_debug(
        "intent_selected",
        intent=intent_result.intent,
        confidence=intent_result.confidence,
        reason=intent_result.reason,
        reference=intent_result.reference.to_debug_dict(),
        requested_doc_code=requested_doc_code,
    )

    if _is_table_request(search_message) or intent_result.intent == "table_lookup":
        table, table_number, doc_code, candidates = _find_table_for_query(db, search_message, requested_doc_code)
        if not table_number:
            meta = {"type": "clarification", "missing_case": "missing_table_number", "model": settings.CHAT_MODEL, "query_language": detected_language}
            _attach_timing_meta(meta, timings, started_at)
            return {"answer": "Qaysi jadval nazarda tutilmoqda? (masalan: 9-jadval)", "sources": [], "table_html": None, "image_urls": [], "meta": meta}
        if not doc_code:
            docs = _table_candidate_docs(db, table_number)
            if table and table.document and table.document.code:
                doc_code = table.document.code
            elif len(docs) == 1 and table:
                doc_code = docs[0]
            elif settings.RAG_ALLOW_DOCUMENT_SUGGESTIONS and docs:
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
            else:
                meta = {
                    "type": "no_match",
                    "target": "table",
                    "reason": "table_document_not_determined",
                    "model": settings.CHAT_MODEL,
                    "query_language": detected_language,
                }
                _attach_timing_meta(meta, timings, started_at)
                return {
                    "answer": f"{table_number}-jadval bo'yicha aniq hujjat topilmadi. Iltimos, SHNQ kodini ham yozing (masalan: SHNQ 2.01.05-24).",
                    "sources": [],
                    "table_html": None,
                    "image_urls": [],
                    "meta": meta,
                }
        if not table and candidates:
            chapters = _table_candidate_chapters(candidates)
            chapter_hint = f" Variantlar: {', '.join(chapters)}." if chapters else ""
            if settings.RAG_ALLOW_DOCUMENT_SUGGESTIONS and chapters:
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
            meta = {
                "type": "no_match",
                "target": "table",
                "reason": "table_chapter_ambiguous",
                "model": settings.CHAT_MODEL,
                "query_language": detected_language,
            }
            _attach_timing_meta(meta, timings, started_at)
            return {
                "answer": f"{table_number}-jadval bir nechta bo'limda uchraydi. SHNQ kodi bilan birga so'rang.",
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
            "intent": intent_result.intent,
            "exact_reference": exact_reference.to_debug_dict(),
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

    def compute_candidates(
        query_text: str,
    ) -> tuple[list[RetrievalItem], list[RetrievalItem], list[RetrievalItem], list[str], MetadataFilters, dict[str, object]]:
        t_embed = time.perf_counter()
        query_vec = embed_text(query_text)
        timings["embed"] = round(timings["embed"] + ((time.perf_counter() - t_embed) * 1000), 2)
        route_result = route_documents(
            db=db,
            query=query_text,
            query_vec=query_vec,
            requested_doc_code=requested_doc_code,
            explicit_doc_codes=exact_reference.document_codes,
        )
        selected_doc_codes = route_result.document_codes
        metadata_filters = _build_metadata_filters(intent_result, exact_reference, selected_doc_codes)
        _log_debug(
            "document_route",
            query=query_text,
            selected_doc_codes=selected_doc_codes,
            route_debug=route_result.debug,
            metadata_filters={
                "document_codes": metadata_filters.document_codes,
                "clause_numbers": metadata_filters.clause_numbers,
                "table_numbers": metadata_filters.table_numbers,
                "appendix_numbers": metadata_filters.appendix_numbers,
                "content_types": metadata_filters.content_types,
            },
        )

        exact_clause_items: list[RetrievalItem] = []
        if intent_result.intent == "exact_band_reference":
            exact_clause_items = _search_exact_clause_references(
                db=db,
                reference=exact_reference,
                document_codes=selected_doc_codes,
                metadata_filters=metadata_filters,
            )
        clause_items = _search_clause_candidates(
            db=db,
            query=query_text,
            query_vec=query_vec,
            doc_codes=selected_doc_codes,
            metadata_filters=metadata_filters,
        )
        if exact_clause_items:
            clause_items = _merge_retrieval_candidates(exact_clause_items, clause_items, secondary_weight=0.96)
        if not clause_items:
            raw_q = db.query(Clause).options(joinedload(Clause.document))
            if selected_doc_codes:
                if len(selected_doc_codes) == 1:
                    raw_q = raw_q.filter(Clause.document.has(code=selected_doc_codes[0]))
                else:
                    raw_q = raw_q.filter(Clause.document.has(Document.code.in_(selected_doc_codes)))
            raw_rows = raw_q.order_by(Clause.order).limit(4000).all()
            words = _extract_query_terms(query_text)
            keyword_hits: list[RetrievalItem] = []
            for row in raw_rows:
                text_l = _normalize_text(row.text or "")
                if not words:
                    break
                tf = sum(text_l.count(w) for w in words)
                coverage = sum(1 for w in words if w in text_l)
                if coverage <= 0:
                    continue
                if coverage == 1 and len(words) >= 4 and tf < 2:
                    continue
                keyword_ratio = coverage / max(len(words), 1)
                score = (keyword_ratio * 0.75) + min(0.25, tf * 0.04)
                keyword_hits.append(
                    RetrievalItem(
                        kind="clause",
                        score=float(score),
                        title=f"Band {row.clause_number or '-'}",
                        snippet=(row.text or "")[:900],
                        shnq_code=row.document.code if row.document else "",
                        document_id=str(row.document_id) if row.document_id else None,
                        section_id=str(row.chapter_id) if row.chapter_id else None,
                        section_title=row.chapter.title if row.chapter else None,
                        content_type="clause",
                        clause_id=str(row.id),
                        clause_number=row.clause_number,
                        html_anchor=row.html_anchor,
                        chapter=row.chapter.title if row.chapter else None,
                        lex_url=row.document.lex_url if row.document else None,
                        semantic_score=0.0,
                        keyword_score=float(keyword_ratio),
                    )
                )
            keyword_hits.sort(key=lambda x: x.score, reverse=True)
            clause_items = [item for item in keyword_hits if match_item_filters(item, metadata_filters)][: settings.RAG_TOP_K]

        clause_best_score = clause_items[0].score if clause_items else 0.0
        normalized_query = _normalize_text(query_text)
        row_priority = _is_table_row_priority_query(query_text)
        table_intent = intent_result.intent == "table_lookup" or _is_table_intent_query(query_text)
        explicit_clause_lookup = _is_explicit_clause_lookup(query_text)
        numeric_requirement = _is_numeric_requirement_query(query_text)
        allow_table_search = (table_intent or row_priority) and not explicit_clause_lookup
        soft_table_probe = (
            (not allow_table_search)
            and numeric_requirement
            and (not explicit_clause_lookup)
            and clause_best_score < settings.RAG_RICH_SOURCE_CLAUSE_THRESHOLD
        )

        row_items: list[RetrievalItem] = []
        if allow_table_search or soft_table_probe:
            row_top_k = settings.RAG_TABLE_INTENT_ROW_TOP_K if table_intent else settings.RAG_TABLE_ROW_TOP_K
            if soft_table_probe:
                row_top_k = min(max(2, row_top_k), 3)
            row_items = _search_table_row_candidates(
                db,
                query_text,
                query_vec,
                selected_doc_codes,
                metadata_filters=metadata_filters,
                row_priority=row_priority,
                limit_override=row_top_k,
            )
            if soft_table_probe:
                strict_score = max(0.42, settings.RAG_TABLE_ROW_MIN_SCORE + 0.18)
                row_items = [
                    item
                    for item in row_items
                    if item.score >= strict_score and float(item.keyword_score or 0.0) >= 0.28
                ]
            if allow_table_search and (row_priority or not row_items):
                row_fallback = _search_table_row_keyword_fallback(
                    db,
                    query_text,
                    selected_doc_codes,
                    limit=max(row_top_k, 8),
                    metadata_filters=metadata_filters,
                )
                if row_fallback:
                    row_items = _merge_retrieval_candidates(row_items, row_fallback, secondary_weight=1.05)

        image_intent = intent_result.intent == "image_lookup" or any(h in normalized_query for h in ["rasm", "image", "diagramma", "sxema", "surat", "chizma"])
        need_image_sources = image_intent or clause_best_score < settings.RAG_MIN_SCORE
        image_items = (
            _search_image_candidates(db, query_text, query_vec, selected_doc_codes, metadata_filters=metadata_filters)
            if need_image_sources
            else []
        )
        if image_items and not image_intent:
            image_items = [
                item
                for item in image_items
                if item.score >= max(settings.RAG_IMAGE_MIN_SCORE + 0.08, 0.3)
            ]
        _log_debug(
            "candidate_counts",
            query=query_text,
            clause=len(clause_items),
            table_row=len(row_items),
            image=len(image_items),
            top_clause_score=round(clause_best_score, 4),
        )
        return clause_items, row_items, image_items, selected_doc_codes, metadata_filters, route_result.debug

    clause_items, row_items, image_items, selected_docs_primary, _metadata_filters_primary, route_debug_primary = compute_candidates(rewritten_primary)
    primary_best_score = clause_items[0].score if clause_items else 0.0
    can_try_translated_fallback = (
        secondary_query_message
        and secondary_query_message.strip()
        and secondary_query_message.strip().lower() != primary_query_message.strip().lower()
    )
    if can_try_translated_fallback and ((not clause_items) or primary_best_score < settings.RAG_TRANSLATION_FALLBACK_THRESHOLD):
        rewritten_secondary = _rewrite_query_if_needed(secondary_query_message)
        sec_clause, sec_rows, sec_images, sec_docs, _sec_filters, sec_route_debug = compute_candidates(rewritten_secondary)
        if sec_clause:
            clause_items = _merge_retrieval_candidates(clause_items, sec_clause, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)
            translation_fallback_used = True
            _log_debug("secondary_clause_merge", selected_docs=sec_docs, route_debug=sec_route_debug, count=len(sec_clause))
        if sec_rows:
            row_items = _merge_retrieval_candidates(row_items, sec_rows, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)
        if sec_images:
            image_items = _merge_retrieval_candidates(image_items, sec_images, secondary_weight=settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT)

    if requested_doc_code and not clause_items and not image_items and not row_items:
        _log_debug("no_answer_trigger", reason="requested_document_no_items", requested_doc_code=requested_doc_code)
        meta = {"type": "no_match", "target": "document", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": f"{requested_doc_code} bo'yicha mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    best_score = clause_items[0].score if clause_items else 0.0
    if not requested_doc_code:
        ask_doc, docs = _should_ask_document_clarification(clause_items, best_score)
        if ask_doc and intent_result.intent == "compare_documents":
            ask_doc = False
        if ask_doc:
            if settings.RAG_ALLOW_DOCUMENT_SUGGESTIONS:
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
            else:
                top_doc = (clause_items[0].shnq_code or "").strip() if clause_items else ""
                if top_doc:
                    clause_items = [item for item in clause_items if (item.shnq_code or "").strip().lower() == top_doc.lower()]
                    row_items = [item for item in row_items if (item.shnq_code or "").strip().lower() == top_doc.lower()]
                    image_items = [item for item in image_items if (item.shnq_code or "").strip().lower() == top_doc.lower()]
                    best_score = clause_items[0].score if clause_items else 0.0

    if _is_weak_clause_only_result(clause_items, row_items, image_items):
        _log_debug("no_answer_trigger", reason="weak_clause_only_result")
        if requested_doc_code:
            message_text = f"{requested_doc_code} bo'yicha savolga mos band aniq topilmadi."
        else:
            message_text = "Savolga mos band aniq topilmadi. Iltimos, SHNQ kodini yoki aniqroq iborani kiriting."
        meta = {
            "type": "no_match",
            "reason": "weak_clause_match",
            "model": settings.CHAT_MODEL,
            "query_language": detected_language,
        }
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": message_text, "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    relaxed = _can_answer_with_relaxed_threshold(clause_items, best_score)
    if best_score < settings.RAG_STRICT_MIN_SCORE and not (relaxed or row_items or image_items):
        clarification = _needs_clarification(search_message)
        if clarification:
            code, question = clarification
            meta = {"type": "clarification", "missing_case": code, "model": settings.CHAT_MODEL, "query_language": detected_language}
            _attach_timing_meta(meta, timings, started_at)
            return {"answer": question, "sources": [], "table_html": None, "image_urls": [], "meta": meta}
        meta = {"type": "no_match", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _log_debug("no_answer_trigger", reason="best_score_below_strict_without_support", best_score=best_score)
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": "Mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    all_candidates = [*clause_items, *row_items, *image_items]
    rerank_debug = {"before_count": len(all_candidates), "after_count": len(all_candidates), "removed_duplicates": 0}
    if settings.RAG_ENABLE_UNIFIED_RERANK:
        reranked_items, reranked_debug = rerank_mixed_items(
            query=original_message,
            items=all_candidates,
            intent=intent_result,
            reference=exact_reference,
            limit=max(settings.RAG_FINAL_K, settings.RAG_TOP_K),
            duplicate_sim_threshold=settings.RAG_DUPLICATE_SIM_THRESHOLD,
        )
        merged_all = reranked_items
        rerank_debug = {
            "before_count": reranked_debug.before_count,
            "after_count": reranked_debug.after_count,
            "removed_duplicates": reranked_debug.removed_duplicates,
        }
        _log_debug(
            "unified_rerank",
            debug=rerank_debug,
            top_after=[
                {
                    "kind": item.kind,
                    "doc": item.shnq_code,
                    "score": round(item.score, 4),
                    "id": item.clause_id or item.table_id or item.image_id,
                }
                for item in merged_all[:5]
            ],
        )
    else:
        merged_all = sorted(all_candidates, key=lambda x: x.score, reverse=True)[: settings.RAG_FINAL_K]

    confidence = assess_confidence(
        items=merged_all if merged_all else clause_items,
        strict_min_score=settings.RAG_STRICT_MIN_SCORE,
        min_score=settings.RAG_MIN_SCORE,
        intent=intent_result,
        reference=exact_reference,
    )
    _log_debug("confidence_assessed", confidence=confidence.to_dict())
    if confidence.no_answer and not (row_items or image_items) and not relaxed:
        message_text = "Kontekstda yetarli ishonchli dalil topilmadi. Iltimos, savolni aniqroq yozing."
        if confidence.reason == "exact_clause_not_found" and exact_reference.clause_numbers:
            message_text = f"{', '.join(exact_reference.clause_numbers)} band bo'yicha aniq moslik topilmadi."
        meta = {
            "type": "no_match",
            "reason": confidence.reason,
            "confidence": confidence.to_dict(),
            "model": settings.CHAT_MODEL,
            "query_language": detected_language,
        }
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": message_text, "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    merged = _select_context_items(original_message, merged_all)
    _hydrate_clause_items(db, merged)
    if not merged:
        meta = {"type": "no_match", "model": settings.CHAT_MODEL, "query_language": detected_language}
        _attach_timing_meta(meta, timings, started_at)
        return {"answer": "Mos band topilmadi.", "sources": [], "table_html": None, "image_urls": [], "meta": meta}

    fewshot_examples = _pick_fewshot_examples(original_message, limit=3)
    system, prompt = _build_rag_prompt(
        original_message,
        merged,
        response_language=detected_language,
        fewshot_examples=fewshot_examples,
        intent=intent_result,
    )

    # LLM chaqiruvi vaqtida DB connectionni band qilib turmaslik uchun
    # read-only transactionni yakunlaymiz.
    try:
        db.rollback()
    except Exception:
        pass

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
        error_text = (str(exc) or "").lower()
        non_retryable = any(
            token in error_text
            for token in ["model not found", "does not exist", "unknown model", "invalid model"]
        )
        if non_retryable:
            llm_error = "primary_generate_failed_non_retryable"
            answer = merged[0].snippet if merged else _empty_answer_text(detected_language)
        else:
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
    top_clause = clause_items[0] if clause_items else None
    meta = {
        "type": "rag",
        "model": settings.CHAT_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "answer_language": detected_language,
        "query_language": detected_language,
        "intent": intent_result.intent,
        "intent_confidence": round(intent_result.confidence, 4),
        "intent_reason": intent_result.reason,
        "exact_reference": exact_reference.to_debug_dict(),
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
        "document_route_primary": selected_docs_primary,
        "document_route_debug_primary": route_debug_primary,
        "multilingual_native_first": settings.RAG_MULTILINGUAL_NATIVE_FIRST,
        "translation_fallback_used": translation_fallback_used,
        "translation_fallback_threshold": settings.RAG_TRANSLATION_FALLBACK_THRESHOLD,
        "translated_query_score_weight": settings.RAG_TRANSLATED_QUERY_SCORE_WEIGHT,
        "document_suggestions_enabled": settings.RAG_ALLOW_DOCUMENT_SUGGESTIONS,
        "fewshot_examples_used": len(fewshot_examples),
        "image_sources": len([i for i in merged if i.kind == "image"]),
        "table_row_sources": len([i for i in merged if i.kind == "table_row"]),
        "table_intent": _is_table_intent_query(search_message),
        "table_prelocalized": _has_pretranslated_table_content(related_table, detected_language),
        "table_row_scan_limit": settings.RAG_TABLE_ROW_SCAN_LIMIT,
        "table_intent_row_top_k": settings.RAG_TABLE_INTENT_ROW_TOP_K,
        "rich_source_clause_threshold": settings.RAG_RICH_SOURCE_CLAUSE_THRESHOLD,
        "retrieval_counts": {
            "clause": len(clause_items),
            "table_row": len(row_items),
            "image": len(image_items),
        },
        "confidence": confidence.to_dict(),
        "rerank_debug": rerank_debug,
        "top_clause_signal": {
            "semantic": round(float(top_clause.semantic_score or 0.0), 4) if top_clause else 0.0,
            "keyword": round(float(top_clause.keyword_score or 0.0), 4) if top_clause else 0.0,
            "doc": top_clause.shnq_code if top_clause else None,
        },
        "best_score": round(best_score, 4),
        "qdrant_enabled": settings.RAG_USE_QDRANT,
        "llm_used": llm_used,
        "llm_error": llm_error,
        "llm_error_detail": llm_error_detail,
    }
    if confidence.warning:
        meta["warning"] = confidence.warning
    _attach_timing_meta(meta, timings, started_at)

    return {"answer": answer, "sources": sources, "table_html": table_html, "image_urls": image_urls, "meta": meta}
