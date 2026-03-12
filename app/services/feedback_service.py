from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.rejected_qa import RejectedQA
from app.models.verified_qa import VerifiedQA
from app.services.llm_service import embed_text
from app.utils.text_fix import repair_mojibake

_APOSTROPHE_VARIANTS = str.maketrans(
    {
        "`": "'",
        "\u2019": "'",
        "\u2018": "'",
        "\u02bc": "'",
        "\u02bb": "'",
        "\u2032": "'",
    }
)

_SHORT_ANSWER_SPLIT_RE = re.compile(r"(qisqa qilib aytganda:|in short:)", re.IGNORECASE)


@dataclass
class VerifiedAnswerHit:
    row: VerifiedQA
    similarity: float
    mode: str


@dataclass
class NegativeFeedbackSignal:
    doc_penalties: dict[str, float]
    source_penalties: set[str]


def normalize_question(text: str) -> str:
    repaired = repair_mojibake(text or "")
    value = unicodedata.normalize("NFKC", repaired).strip().lower()
    value = value.translate(_APOSTROPHE_VARIANTS)
    return re.sub(r"\s+", " ", value)


def _normalize_doc_code(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def _safe_embed(value: str) -> list[float]:
    try:
        vec = embed_text(value)
        return vec if isinstance(vec, list) else []
    except Exception:
        return []


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def source_ids_from_payload(sources: list | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        item_type = (src.get("type") or "").strip().lower()
        doc = _normalize_doc_code(src.get("shnq_code"))
        if item_type == "clause":
            ref = (src.get("clause_number") or src.get("html_anchor") or "").strip().lower()
            source_id = f"clause:{doc}:{ref}"
        elif item_type == "table_row":
            ref = (src.get("table_number") or "").strip().lower()
            row_index = src.get("row_index")
            source_id = f"table_row:{doc}:{ref}:{row_index}"
        elif item_type == "table":
            ref = (src.get("table_number") or "").strip().lower()
            source_id = f"table:{doc}:{ref}"
        elif item_type == "image":
            ref = (src.get("appendix_number") or src.get("image_url") or "").strip().lower()
            source_id = f"image:{doc}:{ref}"
        else:
            ref = (src.get("title") or src.get("snippet") or "").strip().lower()[:64]
            source_id = f"{item_type or 'source'}:{doc}:{ref}"
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(source_id)
    return out


def primary_document_code(sources: list | None) -> str | None:
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        code = (src.get("shnq_code") or "").strip()
        if code:
            return code
    return None


def short_answer(answer: str) -> str:
    text = (answer or "").strip()
    if not text:
        return ""
    parts = _SHORT_ANSWER_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) >= 3:
        short = parts[2].strip()
        if short:
            return short[:400]
    first_sentence = re.split(r"[.!?](?:\s|$)", text, maxsplit=1)[0].strip()
    return (first_sentence or text)[:400]


def _source_hash(source_ids: list[str]) -> str:
    payload = json.dumps(sorted(source_ids), ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def upsert_verified_qa(
    db: Session,
    question: str,
    answer: str,
    sources: list | None,
    language: str | None = None,
    intent_type: str | None = None,
) -> VerifiedQA:
    normalized = normalize_question(question)
    ids = source_ids_from_payload(sources)
    doc_code = primary_document_code(sources)
    hash_value = _source_hash(ids)
    row = (
        db.query(VerifiedQA)
        .filter(
            VerifiedQA.normalized_question == normalized,
            VerifiedQA.source_hash == hash_value,
            VerifiedQA.answer == answer,
        )
        .order_by(VerifiedQA.updated_at.desc())
        .first()
    )
    now = datetime.utcnow()
    if row:
        row.verified_count = int(row.verified_count or 0) + 1
        row.verified_by_user = True
        row.verified_at = now
        row.updated_at = now
        row.source_payload = sources or []
        row.source_ids = ids
        if language:
            row.language = language
        if intent_type:
            row.intent_type = intent_type
        if doc_code:
            row.document_code = doc_code
        return row

    row = VerifiedQA(
        normalized_question=normalized,
        original_question=question,
        answer=answer,
        short_answer=short_answer(answer),
        document_code=doc_code,
        source_ids=ids,
        source_payload=sources or [],
        embedding=_safe_embed(question),
        language=language,
        intent_type=intent_type,
        source_hash=hash_value,
        verified_by_user=True,
        verified_count=1,
        is_active=True,
        verified_at=now,
    )
    db.add(row)
    return row


def upsert_rejected_qa(
    db: Session,
    question: str,
    answer: str,
    sources: list | None,
    reason: str | None = None,
) -> RejectedQA:
    normalized = normalize_question(question)
    ids = source_ids_from_payload(sources)
    doc_code = primary_document_code(sources)
    row = (
        db.query(RejectedQA)
        .filter(
            RejectedQA.normalized_question == normalized,
            RejectedQA.rejected_answer == answer,
        )
        .order_by(RejectedQA.updated_at.desc())
        .first()
    )
    now = datetime.utcnow()
    if row:
        row.rejected_count = int(row.rejected_count or 0) + 1
        row.rejected_at = now
        row.updated_at = now
        row.rejected_source_ids = ids
        row.rejected_source_payload = sources or []
        row.document_code = doc_code
        if reason:
            row.reason = reason
        return row

    row = RejectedQA(
        normalized_question=normalized,
        original_question=question,
        rejected_answer=answer,
        rejected_source_ids=ids,
        rejected_source_payload=sources or [],
        document_code=doc_code,
        reason=reason,
        embedding=_safe_embed(question),
        rejected_count=1,
        rejected_at=now,
    )
    db.add(row)
    return row


def find_verified_answer_hit(
    db: Session,
    question: str,
    requested_doc_code: str | None = None,
    exact_only: bool = False,
) -> VerifiedAnswerHit | None:
    normalized = normalize_question(question)
    requested_doc = _normalize_doc_code(requested_doc_code)
    has_any_verified = db.query(VerifiedQA.id).filter(VerifiedQA.is_active.is_(True)).limit(1).first()
    if not has_any_verified:
        return None

    exact_rows = (
        db.query(VerifiedQA)
        .filter(VerifiedQA.is_active.is_(True), VerifiedQA.normalized_question == normalized)
        .order_by(VerifiedQA.verified_count.desc(), VerifiedQA.updated_at.desc())
        .limit(15)
        .all()
    )
    if exact_rows:
        if requested_doc:
            same_doc = [row for row in exact_rows if _normalize_doc_code(row.document_code) == requested_doc]
            if same_doc:
                return VerifiedAnswerHit(row=same_doc[0], similarity=1.0, mode="exact")
            return None
        return VerifiedAnswerHit(row=exact_rows[0], similarity=1.0, mode="exact")

    if exact_only:
        return None

    q_vec = _safe_embed(question)
    if not q_vec:
        return None
    rows = (
        db.query(VerifiedQA)
        .filter(VerifiedQA.is_active.is_(True), VerifiedQA.embedding.isnot(None))
        .order_by(VerifiedQA.verified_count.desc(), VerifiedQA.updated_at.desc())
        .limit(500)
        .all()
    )
    best: VerifiedAnswerHit | None = None
    for row in rows:
        if requested_doc and _normalize_doc_code(row.document_code) != requested_doc:
            continue
        candidate_vec = row.embedding if isinstance(row.embedding, list) else []
        sim = _cosine(q_vec, candidate_vec)
        if sim < 0.9:
            continue
        if best is None or sim > best.similarity:
            best = VerifiedAnswerHit(row=row, similarity=sim, mode="semantic")
    return best


def get_negative_feedback_signal(db: Session, question: str) -> NegativeFeedbackSignal:
    normalized = normalize_question(question)
    rows = (
        db.query(RejectedQA)
        .filter(RejectedQA.normalized_question == normalized)
        .order_by(RejectedQA.rejected_at.desc(), RejectedQA.updated_at.desc())
        .limit(80)
        .all()
    )
    if not rows:
        has_any_rejected = db.query(RejectedQA.id).limit(1).first()
        if not has_any_rejected:
            return NegativeFeedbackSignal(doc_penalties={}, source_penalties=set())
        q_vec = _safe_embed(question)
        if q_vec:
            candidates = (
                db.query(RejectedQA)
                .filter(RejectedQA.embedding.isnot(None))
                .order_by(RejectedQA.rejected_at.desc(), RejectedQA.updated_at.desc())
                .limit(400)
                .all()
            )
            scored: list[tuple[float, RejectedQA]] = []
            for row in candidates:
                vec = row.embedding if isinstance(row.embedding, list) else []
                sim = _cosine(q_vec, vec)
                if sim >= 0.92:
                    scored.append((sim, row))
            scored.sort(key=lambda x: x[0], reverse=True)
            rows = [row for _, row in scored[:60]]

    doc_penalties: dict[str, float] = {}
    source_penalties: set[str] = set()
    for row in rows:
        base = 0.12
        repeat_boost = min(0.28, max(0, int(row.rejected_count or 1) - 1) * 0.05)
        penalty = base + repeat_boost
        doc_key = _normalize_doc_code(row.document_code)
        if doc_key:
            doc_penalties[doc_key] = min(0.58, doc_penalties.get(doc_key, 0.0) + penalty)
        for source_id in row.rejected_source_ids or []:
            if isinstance(source_id, str) and source_id.strip():
                source_penalties.add(source_id.strip())
    return NegativeFeedbackSignal(doc_penalties=doc_penalties, source_penalties=source_penalties)
