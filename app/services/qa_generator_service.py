from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.clause import Clause
from app.models.document import Document
from app.models.norm_table import NormTable
from app.models.qa_generated_draft import QAGeneratedDraft
from app.models.qa_generation_job import QAGenerationJob
from app.models.verified_qa import VerifiedQA
from app.services.feedback_service import normalize_question, upsert_verified_qa
from app.services.llm_service import embed_text, generate_json


PROMPT_VERSION = settings.QA_GENERATOR_PROMPT_VERSION
ACTIVE_JOB_STATUSES = {"queued", "running"}
QUESTION_DUPLICATE_RE = re.compile(r"\s+")
TABLE_NUMBER_HINT_RE = re.compile(r"\b(\d+(?:\.\d+)*[a-z]?)\b", re.IGNORECASE)
QUALITY_TERMS = {
    "kerak",
    "lozim",
    "mumkin",
    "taqiqlanadi",
    "kamida",
    "ko'pi",
    "maksimal",
    "minimal",
    "foiz",
    "metr",
    "mm",
    "sm",
    "jadval",
    "talab",
}
GENERATOR_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["document_code", "document_title", "items"],
    "properties": {
        "document_code": {"type": "string"},
        "document_title": {"type": "string"},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "question",
                    "answer",
                    "short_answer",
                    "chapter_title",
                    "clause_number",
                    "has_table",
                    "table_number",
                    "table_title",
                    "lex_url",
                    "source_excerpt",
                    "source_anchor",
                    "source_kind",
                ],
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "short_answer": {"type": "string"},
                    "chapter_title": {"type": "string"},
                    "clause_number": {"type": "string"},
                    "has_table": {"type": "boolean"},
                    "table_number": {"type": ["string", "null"]},
                    "table_title": {"type": ["string", "null"]},
                    "lex_url": {"type": ["string", "null"]},
                    "source_excerpt": {"type": "string"},
                    "source_anchor": {"type": "string"},
                    "source_kind": {"type": "string"},
                },
            },
        },
    },
}


def _clean_text(value: str | None) -> str:
    return QUESTION_DUPLICATE_RE.sub(" ", (value or "").strip())


def _is_active_job_status(status: str | None) -> bool:
    return (status or "").strip().lower() in ACTIVE_JOB_STATUSES


def cleanup_stale_jobs(db: Session) -> int:
    threshold = datetime.utcnow() - timedelta(minutes=max(1, int(settings.QA_GENERATOR_STALE_MINUTES)))
    stale_jobs = (
        db.query(QAGenerationJob)
        .filter(QAGenerationJob.status.in_(tuple(ACTIVE_JOB_STATUSES)))
        .all()
    )
    changed = 0
    for job in stale_jobs:
        last_touch = job.updated_at or job.created_at
        if not last_touch or last_touch >= threshold:
            continue
        job.status = "failed"
        if not job.error_message:
            job.error_message = (
                "Generator job timeout bo'ldi yoki server restart sabab to'xtab qoldi. "
                "Jobni o'chirib qayta ishga tushiring."
            )
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        changed += 1
    if changed:
        db.commit()
    return changed


def _normalize_table_number(value: str | None) -> str:
    return re.sub(r"[\s,._-]+", ".", (value or "").strip().lower()).strip(".")


def _looks_useful(text: str | None, *, minimum: int = 40) -> bool:
    value = _clean_text(text)
    return len(value) >= minimum


def _score_clause(text: str | None) -> float:
    cleaned = _clean_text(text)
    if not cleaned:
        return 0.0
    digit_bonus = min(3, len(re.findall(r"\d", cleaned))) * 0.12
    quality_bonus = sum(0.08 for term in QUALITY_TERMS if term in cleaned.lower())
    length_bonus = min(len(cleaned), 900) / 900 * 0.25
    return digit_bonus + quality_bonus + length_bonus


def _score_table(table: NormTable) -> float:
    haystack = _clean_text(
        " ".join(
            [
                table.table_number or "",
                table.title or "",
                table.section_title or "",
                table.markdown or table.raw_html or "",
            ]
        )
    )
    if not haystack:
        return 0.0
    digit_bonus = min(6, len(re.findall(r"\d", haystack))) * 0.06
    quality_bonus = sum(0.08 for term in QUALITY_TERMS if term in haystack.lower())
    return digit_bonus + quality_bonus + 0.3


def _table_content(table: NormTable) -> tuple[str, str]:
    html = (table.raw_html or "").strip()
    markdown = (table.markdown or "").strip()
    if not markdown and html:
        markdown = re.sub(r"<[^>]+>", " ", html)
        markdown = _clean_text(markdown)
    return html, markdown


def search_documents_for_generator(db: Session, query: str, limit: int = 15) -> list[dict[str, object]]:
    cleaned = _clean_text(query)
    document_query = db.query(Document)
    if cleaned:
        like = f"%{cleaned}%"
        document_query = document_query.filter(or_(Document.code.ilike(like), Document.title.ilike(like)))
    documents = document_query.order_by(Document.code.asc(), Document.title.asc()).limit(limit).all()
    if not documents:
        return []

    ids = [doc.id for doc in documents]
    clause_counts = {
        str(row[0]): int(row[1] or 0)
        for row in db.query(Clause.document_id, func.count(Clause.id)).filter(Clause.document_id.in_(ids)).group_by(Clause.document_id).all()
    }
    table_counts = {
        str(row[0]): int(row[1] or 0)
        for row in db.query(NormTable.document_id, func.count(NormTable.id)).filter(NormTable.document_id.in_(ids)).group_by(NormTable.document_id).all()
    }
    approved_counts = {
        str(row[0]): int(row[1] or 0)
        for row in db.query(VerifiedQA.document_id, func.count(VerifiedQA.id))
        .filter(VerifiedQA.document_id.in_(ids), VerifiedQA.is_active.is_(True))
        .group_by(VerifiedQA.document_id)
        .all()
    }
    return [
        {
            "id": str(doc.id),
            "code": doc.code,
            "title": doc.title,
            "lex_url": doc.lex_url,
            "clause_count": clause_counts.get(str(doc.id), 0),
            "table_count": table_counts.get(str(doc.id), 0),
            "approved_count": approved_counts.get(str(doc.id), 0),
        }
        for doc in documents
    ]


def get_document_generator_context(db: Session, document_id: str) -> dict[str, object]:
    cleanup_stale_jobs(db)
    document_uuid = uuid.UUID(document_id)
    document = (
        db.query(Document)
        .options(joinedload(Document.tables), joinedload(Document.clauses), joinedload(Document.category))
        .filter(Document.id == document_uuid)
        .first()
    )
    if not document:
        raise ValueError("SHNQ topilmadi.")
    latest_job = (
        db.query(QAGenerationJob)
        .filter(QAGenerationJob.document_id == document.id)
        .order_by(QAGenerationJob.created_at.desc())
        .first()
    )
    return {
        "id": str(document.id),
        "code": document.code,
        "title": document.title,
        "lex_url": document.lex_url,
        "category": document.category.name if document.category else None,
        "clause_count": len(document.clauses or []),
        "table_count": len(document.tables or []),
        "approved_count": db.query(func.count(VerifiedQA.id))
        .filter(VerifiedQA.document_id == document.id, VerifiedQA.is_active.is_(True))
        .scalar()
        or 0,
        "latest_job": _serialize_job(latest_job) if latest_job else None,
    }


def create_generation_job(
    db: Session,
    *,
    document_id: str,
    requested_count: int,
    include_table_questions: bool,
    created_by: str | None = None,
) -> QAGenerationJob:
    document = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
    if not document:
        raise ValueError("SHNQ topilmadi.")
    job = QAGenerationJob(
        document_id=document.id,
        document_code=document.code,
        document_title=document.title,
        requested_count=max(1, requested_count),
        generated_count=0,
        approved_count=0,
        include_table_questions=include_table_questions,
        status="queued",
        generator_model=settings.QA_GENERATOR_MODEL,
        prompt_version=PROMPT_VERSION,
        created_by=created_by,
    )
    db.add(job)
    db.flush()
    return job


def _collect_clause_items(db: Session, document_id: uuid.UUID) -> list[dict[str, object]]:
    clauses = (
        db.query(Clause)
        .options(joinedload(Clause.chapter), joinedload(Clause.document))
        .filter(Clause.document_id == document_id)
        .order_by(Clause.order.asc(), Clause.clause_number.asc())
        .all()
    )
    ranked: list[tuple[float, dict[str, object]]] = []
    for clause in clauses:
        excerpt = _clean_text(clause.text)
        if not _looks_useful(excerpt):
            continue
        score = _score_clause(excerpt)
        ranked.append(
            (
                score,
                {
                    "kind": "clause",
                    "chapter_title": clause.chapter.title if clause.chapter else "",
                    "clause_number": clause.clause_number or "",
                    "source_anchor": clause.html_anchor or "",
                    "source_excerpt": excerpt[: settings.QA_GENERATOR_MAX_CLAUSE_CHARS],
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked]


def _collect_table_items(db: Session, document_id: uuid.UUID) -> list[dict[str, object]]:
    tables = (
        db.query(NormTable)
        .options(joinedload(NormTable.chapter), joinedload(NormTable.document))
        .filter(NormTable.document_id == document_id)
        .order_by(NormTable.order.asc(), NormTable.table_number.asc())
        .all()
    )
    ranked: list[tuple[float, dict[str, object]]] = []
    for table in tables:
        html, markdown = _table_content(table)
        excerpt = _clean_text(markdown or re.sub(r"<[^>]+>", " ", html))
        if not _looks_useful(excerpt):
            continue
        score = _score_table(table)
        ranked.append(
            (
                score,
                {
                    "kind": "table",
                    "chapter_title": table.section_title or (table.chapter.title if table.chapter else ""),
                    "clause_number": "",
                    "source_anchor": table.html_anchor or "",
                    "source_excerpt": excerpt[: settings.QA_GENERATOR_MAX_TABLE_CHARS],
                    "table_number": table.table_number or "",
                    "table_title": table.title or "",
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked]


def _pick_context_window(
    clause_items: list[dict[str, object]],
    table_items: list[dict[str, object]],
    *,
    offset: int,
    batch_count: int,
    include_table_questions: bool,
) -> list[dict[str, object]]:
    max_items = max(settings.QA_GENERATOR_MAX_CONTEXT_ITEMS, batch_count * 2)
    clause_window = clause_items[offset : offset + max_items]
    table_window = table_items[offset : offset + max(3, math.ceil(max_items / 3))]
    if include_table_questions and table_window:
        blend: list[dict[str, object]] = []
        for idx in range(max(len(clause_window), len(table_window))):
            if idx < len(clause_window):
                blend.append(clause_window[idx])
            if idx < len(table_window):
                blend.append(table_window[idx])
        return blend[:max_items]
    window = clause_window[:max_items]
    if not window:
        window = clause_items[:max_items] or table_items[:max_items]
    return window


def _generator_system_prompt() -> str:
    return (
        "Siz SHNQ hujjatlaridan admin knowledge base uchun savol-javob generatorisiz. "
        "Faqat berilgan kontekst ichidan ishlang. Fakt, son, birlik yoki jadvalni uydirmang. "
        "Savollar tabiiy Uzbekcha bo'lsin, rasmiy va kitobiy bo'lmasin. "
        "Kontekstga aloqasiz savollar yaratmang. "
        "Natijani faqat JSON qaytaring."
    )


def _build_generation_prompt(
    *,
    document: Document,
    batch_count: int,
    include_table_questions: bool,
    context_items: list[dict[str, object]],
    existing_questions: set[str],
) -> str:
    examples = "\n".join([f"- savol: {question}" for question in list(existing_questions)[:25]])
    context_lines: list[str] = []
    for idx, item in enumerate(context_items, start=1):
        if item["kind"] == "table":
            context_lines.append(
                f"[T{idx}] chapter={item.get('chapter_title')}; table_number={item.get('table_number')}; "
                f"table_title={item.get('table_title')}; anchor={item.get('source_anchor')}; "
                f"excerpt={item.get('source_excerpt')}"
            )
        else:
            context_lines.append(
                f"[C{idx}] chapter={item.get('chapter_title')}; clause_number={item.get('clause_number')}; "
                f"anchor={item.get('source_anchor')}; excerpt={item.get('source_excerpt')}"
            )
    context_block = "\n".join(context_lines)
    return (
        f"SHNQ kodi: {document.code}\n"
        f"SHNQ nomi: {document.title}\n"
        f"Lex link: {document.lex_url or ''}\n"
        f"Nechta savol kerak: {batch_count}\n"
        f"Jadval savollari kerakmi: {'ha' if include_table_questions else 'yoq'}\n\n"
        "Qoidalar:\n"
        "1. Faqat shu SHNQ konteksti ichidan savol tuzing.\n"
        "2. Savollar real foydalanuvchi tilida bo'lsin: 'qancha bo'lishi kerak', 'mumkinmi', 'jadvalda nechchi', 'qaysi holatda' kabi.\n"
        "3. Takror savollar yaratmang.\n"
        "4. Javob sonlari va birliklarini aynan kontekstdagidek yozing.\n"
        "5. short_answer juda qisqa bo'lsin.\n"
        "6. Jadvalga tayangan bo'lsa has_table=true, table_number va table_title ni to'ldiring.\n"
        "7. Jadval raqami noma'lum bo'lsa bunday savol yaratmang.\n"
        "8. Manba bo'limini chapter_title, clause_number, source_anchor, source_excerpt orqali ko'rsating.\n"
        "9. source_kind faqat clause, table yoki mixed bo'lsin.\n"
        "10. Faqat valid JSON qaytaring.\n\n"
        f"Oldin ishlatilgan savollar, bularni takrorlamang:\n{examples or '- yoq'}\n\n"
        f"Kontekst:\n{context_block}"
    )


def _extract_table_number_from_text(value: str | None) -> str | None:
    match = TABLE_NUMBER_HINT_RE.search(_clean_text(value))
    return match.group(1) if match else None


def _validate_generated_item(
    *,
    raw: dict[str, object],
    document: Document,
    tables_by_number: dict[str, NormTable],
    clause_anchor_by_number: dict[str, str],
) -> dict[str, object] | None:
    question = _clean_text(str(raw.get("question") or ""))
    answer = _clean_text(str(raw.get("answer") or ""))
    short_answer = _clean_text(str(raw.get("short_answer") or ""))
    chapter_title = _clean_text(str(raw.get("chapter_title") or ""))
    clause_number = _clean_text(str(raw.get("clause_number") or ""))
    source_excerpt = _clean_text(str(raw.get("source_excerpt") or ""))
    source_anchor = _clean_text(str(raw.get("source_anchor") or ""))
    source_kind = _clean_text(str(raw.get("source_kind") or "clause")).lower()
    if source_kind not in {"clause", "table", "mixed"}:
        source_kind = "clause"
    if len(question) < 10 or len(answer) < 15 or len(short_answer) < 2 or len(source_excerpt) < 20:
        return None
    has_table = bool(raw.get("has_table"))
    table_number = _clean_text(str(raw.get("table_number") or "")) or None
    if has_table and not table_number:
        table_number = _extract_table_number_from_text(source_excerpt)
    matched_table = tables_by_number.get(_normalize_table_number(table_number)) if table_number else None
    if has_table and not matched_table:
        return None
    if matched_table:
        table_number = matched_table.table_number
    if not source_anchor and clause_number:
        source_anchor = clause_anchor_by_number.get(clause_number, "")
    if matched_table and not source_anchor:
        source_anchor = matched_table.html_anchor or ""
    return {
        "question": question,
        "answer": answer,
        "short_answer": short_answer[:300],
        "document_id": str(document.id),
        "document_code": document.code,
        "chapter_title": chapter_title,
        "clause_number": clause_number,
        "has_table": bool(matched_table),
        "table_id": str(matched_table.id) if matched_table else None,
        "table_number": matched_table.table_number if matched_table else None,
        "table_title": matched_table.title if matched_table else _clean_text(str(raw.get("table_title") or "")) or None,
        "lex_url": _clean_text(str(raw.get("lex_url") or "")) or document.lex_url,
        "source_excerpt": source_excerpt[:900],
        "source_anchor": source_anchor,
        "source_kind": source_kind if matched_table else ("clause" if source_kind != "mixed" else "mixed"),
    }


def _generate_batch(
    *,
    document: Document,
    batch_count: int,
    include_table_questions: bool,
    context_items: list[dict[str, object]],
    existing_questions: set[str],
    tables_by_number: dict[str, NormTable],
    clause_anchor_by_number: dict[str, str],
) -> list[dict[str, object]]:
    prompt = _build_generation_prompt(
        document=document,
        batch_count=batch_count,
        include_table_questions=include_table_questions,
        context_items=context_items,
        existing_questions=existing_questions,
    )
    raw_payload = generate_json(
        prompt=prompt,
        system=_generator_system_prompt(),
        schema=GENERATOR_JSON_SCHEMA,
        model=settings.QA_GENERATOR_MODEL,
        options={"temperature": 0.2, "top_p": 0.95, "max_tokens": 2400},
    )
    if not isinstance(raw_payload, dict):
        return []
    items = raw_payload.get("items")
    if not isinstance(items, list):
        return []
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        parsed = _validate_generated_item(
            raw=item,
            document=document,
            tables_by_number=tables_by_number,
            clause_anchor_by_number=clause_anchor_by_number,
        )
        if not parsed:
            continue
        key = normalize_question(str(parsed["question"]))
        if key in seen or key in existing_questions:
            continue
        seen.add(key)
        validated.append(parsed)
    return validated[:batch_count]


def _existing_questions_for_document(db: Session, document_id: uuid.UUID) -> set[str]:
    existing: set[str] = set()
    draft_questions = db.query(QAGeneratedDraft.question).filter(QAGeneratedDraft.document_id == document_id).all()
    verified_questions = db.query(VerifiedQA.original_question).filter(VerifiedQA.document_id == document_id).all()
    for (value,) in [*draft_questions, *verified_questions]:
        if value:
            existing.add(normalize_question(value))
    return existing


def _persist_drafts(db: Session, job: QAGenerationJob, items: list[dict[str, object]]) -> int:
    created = 0
    for item in items:
        question = str(item["question"])
        duplicate = (
            db.query(QAGeneratedDraft.id)
            .filter(
                QAGeneratedDraft.document_id == job.document_id,
                QAGeneratedDraft.question == question,
            )
            .first()
        )
        if duplicate:
            continue
        draft = QAGeneratedDraft(
            job_id=job.id,
            document_id=job.document_id,
            document_code=job.document_code,
            question=question,
            answer=str(item["answer"]),
            short_answer=str(item["short_answer"]),
            chapter_title=str(item.get("chapter_title") or ""),
            clause_number=str(item.get("clause_number") or "") or None,
            has_table=bool(item.get("has_table")),
            table_id=uuid.UUID(str(item["table_id"])) if item.get("table_id") else None,
            table_number=str(item.get("table_number") or "") or None,
            table_title=str(item.get("table_title") or "") or None,
            lex_url=str(item.get("lex_url") or "") or None,
            source_excerpt=str(item["source_excerpt"]),
            source_anchor=str(item.get("source_anchor") or "") or None,
            source_kind=str(item.get("source_kind") or "clause"),
            generation_model=settings.QA_GENERATOR_MODEL,
            prompt_version=PROMPT_VERSION,
            status="draft",
            embedding=embed_text(question),
            raw_payload=item,
        )
        db.add(draft)
        created += 1
    job.generated_count = int(job.generated_count or 0) + created
    job.updated_at = datetime.utcnow()
    return created


def run_generation_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(QAGenerationJob).filter(QAGenerationJob.id == uuid.UUID(job_id)).first()
        if not job:
            return
        if job.status == "cancelled":
            job.finished_at = job.finished_at or datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
            return
        document = db.query(Document).filter(Document.id == job.document_id).first()
        if not document:
            job.status = "failed"
            job.error_message = "SHNQ topilmadi."
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        clause_items = _collect_clause_items(db, document.id)
        table_items = _collect_table_items(db, document.id)
        if not clause_items and not table_items:
            job.status = "failed"
            job.error_message = "SHNQ uchun generator konteksti topilmadi."
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        job.status = "running"
        job.error_message = None
        job.updated_at = datetime.utcnow()
        db.commit()

        existing_questions = _existing_questions_for_document(db, document.id)
        tables = db.query(NormTable).filter(NormTable.document_id == document.id).all()
        tables_by_number = {_normalize_table_number(table.table_number): table for table in tables}
        clause_anchor_by_number = {
            clause.clause_number or "": clause.html_anchor or ""
            for clause in db.query(Clause).filter(Clause.document_id == document.id).all()
            if clause.clause_number
        }

        remaining = max(1, int(job.requested_count or 1))
        offset = 0
        attempts = 0
        max_attempts = max(4, math.ceil(remaining * 2.5))
        while remaining > 0 and attempts < max_attempts:
            current_job = db.query(QAGenerationJob).filter(QAGenerationJob.id == job.id).first()
            if not current_job:
                return
            if current_job.status == "cancelled":
                current_job.finished_at = current_job.finished_at or datetime.utcnow()
                current_job.updated_at = datetime.utcnow()
                db.commit()
                return
            job = current_job
            job.updated_at = datetime.utcnow()
            db.commit()

            batch_count = min(settings.QA_GENERATOR_BATCH_SIZE, remaining)
            context_items = _pick_context_window(
                clause_items,
                table_items,
                offset=offset,
                batch_count=batch_count,
                include_table_questions=job.include_table_questions,
            )
            offset += batch_count
            attempts += 1
            try:
                generated = _generate_batch(
                    document=document,
                    batch_count=batch_count,
                    include_table_questions=job.include_table_questions,
                    context_items=context_items,
                    existing_questions=existing_questions,
                    tables_by_number=tables_by_number,
                    clause_anchor_by_number=clause_anchor_by_number,
                )
            except Exception as exc:
                job.updated_at = datetime.utcnow()
                job.error_message = f"{type(exc).__name__}: {str(exc)[:400]}"
                db.commit()
                continue

            if not generated:
                continue

            current_job = db.query(QAGenerationJob).filter(QAGenerationJob.id == job.id).first()
            if not current_job:
                return
            if current_job.status == "cancelled":
                current_job.finished_at = current_job.finished_at or datetime.utcnow()
                current_job.updated_at = datetime.utcnow()
                db.commit()
                return
            job = current_job

            created = _persist_drafts(db, job, generated)
            if created:
                for item in generated[:created]:
                    existing_questions.add(normalize_question(str(item["question"])))
                remaining = max(0, remaining - created)
                db.commit()

        job.status = "completed" if int(job.generated_count or 0) > 0 else "failed"
        if job.status == "completed":
            job.error_message = None
        elif not job.error_message:
            job.error_message = "Generator hech qanday valid draft qaytara olmadi."
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def cancel_generation_job(db: Session, job_id: str) -> QAGenerationJob:
    cleanup_stale_jobs(db)
    job = db.query(QAGenerationJob).filter(QAGenerationJob.id == uuid.UUID(job_id)).first()
    if not job:
        raise ValueError("Job topilmadi.")
    if not _is_active_job_status(job.status):
        raise ValueError("Faqat queued yoki running jobni bekor qilish mumkin.")
    job.status = "cancelled"
    job.error_message = "Generator job admin tomonidan bekor qilindi."
    job.finished_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    return job


def delete_generation_job(db: Session, job_id: str) -> None:
    cleanup_stale_jobs(db)
    job = db.query(QAGenerationJob).filter(QAGenerationJob.id == uuid.UUID(job_id)).first()
    if not job:
        raise ValueError("Job topilmadi.")
    if _is_active_job_status(job.status):
        raise ValueError("Running jobni o'chirishdan oldin uni bekor qiling.")
    db.query(QAGeneratedDraft).filter(QAGeneratedDraft.job_id == job.id).delete(synchronize_session=False)
    db.delete(job)


def _build_draft_sources(db: Session, draft: QAGeneratedDraft) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    if draft.source_kind in {"clause", "mixed"} or not draft.has_table:
        sources.append(
            {
                "type": "clause",
                "shnq_code": draft.document_code,
                "document_id": str(draft.document_id),
                "chapter": draft.chapter_title,
                "clause_number": draft.clause_number,
                "html_anchor": draft.source_anchor,
                "lex_url": draft.lex_url,
                "snippet": draft.source_excerpt,
            }
        )
    if draft.table_id:
        table = (
            db.query(NormTable)
            .options(joinedload(NormTable.document), joinedload(NormTable.chapter))
            .filter(NormTable.id == draft.table_id)
            .first()
        )
        if table:
            table_html, table_md = _table_content(table)
            sources.append(
                {
                    "type": "table",
                    "shnq_code": table.document.code if table.document else draft.document_code,
                    "document_id": str(table.document_id) if table.document_id else str(draft.document_id),
                    "chapter": table.section_title or (table.chapter.title if table.chapter else draft.chapter_title),
                    "table_number": table.table_number,
                    "title": table.title,
                    "html_anchor": table.html_anchor,
                    "markdown": table_md,
                    "html": table_html,
                }
            )
    return sources


def approve_draft(db: Session, draft_id: str, review_note: str | None = None) -> VerifiedQA:
    draft = db.query(QAGeneratedDraft).filter(QAGeneratedDraft.id == uuid.UUID(draft_id)).first()
    if not draft:
        raise ValueError("Draft topilmadi.")
    sources = _build_draft_sources(db, draft)
    row = upsert_verified_qa(
        db=db,
        question=draft.question,
        answer=draft.answer,
        sources=sources,
        short_answer_override=draft.short_answer,
        document_id=str(draft.document_id),
        document_code=draft.document_code,
        chapter_title=draft.chapter_title,
        clause_number=draft.clause_number,
        has_table=draft.has_table,
        table_id=str(draft.table_id) if draft.table_id else None,
        table_number=draft.table_number,
        table_title=draft.table_title,
        lex_url=draft.lex_url,
        source_anchor=draft.source_anchor,
        source_excerpt=draft.source_excerpt,
        origin_type="ai_generated",
        generation_job_id=str(draft.job_id),
    )
    draft.status = "approved"
    draft.review_note = review_note
    draft.approved_at = datetime.utcnow()
    draft.updated_at = datetime.utcnow()
    job = db.query(QAGenerationJob).filter(QAGenerationJob.id == draft.job_id).first()
    if job:
        job.approved_count = (
            db.query(func.count(QAGeneratedDraft.id))
            .filter(QAGeneratedDraft.job_id == job.id, QAGeneratedDraft.status == "approved")
            .scalar()
            or 0
        )
        job.updated_at = datetime.utcnow()
    return row


def reject_draft(db: Session, draft_id: str, review_note: str | None = None) -> QAGeneratedDraft:
    draft = db.query(QAGeneratedDraft).filter(QAGeneratedDraft.id == uuid.UUID(draft_id)).first()
    if not draft:
        raise ValueError("Draft topilmadi.")
    draft.status = "rejected"
    draft.review_note = review_note
    draft.updated_at = datetime.utcnow()
    return draft


def list_jobs(
    db: Session,
    *,
    document_id: str | None = None,
    limit: int = 50,
) -> list[QAGenerationJob]:
    cleanup_stale_jobs(db)
    query = db.query(QAGenerationJob)
    if document_id:
        query = query.filter(QAGenerationJob.document_id == uuid.UUID(document_id))
    return query.order_by(QAGenerationJob.created_at.desc()).limit(limit).all()


def list_drafts(
    db: Session,
    *,
    document_id: str | None = None,
    job_id: str | None = None,
    status: str | None = None,
    limit: int = 500,
) -> list[QAGeneratedDraft]:
    query = db.query(QAGeneratedDraft)
    if document_id:
        query = query.filter(QAGeneratedDraft.document_id == uuid.UUID(document_id))
    if job_id:
        query = query.filter(QAGeneratedDraft.job_id == uuid.UUID(job_id))
    if status:
        query = query.filter(QAGeneratedDraft.status == status)
    return query.order_by(QAGeneratedDraft.created_at.desc()).limit(limit).all()


def get_table_preview(db: Session, table_id: str) -> dict[str, object]:
    table = (
        db.query(NormTable)
        .options(joinedload(NormTable.document), joinedload(NormTable.chapter))
        .filter(NormTable.id == uuid.UUID(table_id))
        .first()
    )
    if not table:
        raise ValueError("Jadval topilmadi.")
    html, markdown = _table_content(table)
    return {
        "id": str(table.id),
        "document_code": table.document.code if table.document else "",
        "chapter_title": table.section_title or (table.chapter.title if table.chapter else None),
        "table_number": table.table_number,
        "title": table.title,
        "html_anchor": table.html_anchor,
        "html": html,
        "markdown": markdown,
    }


def _serialize_job(job: QAGenerationJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "document_id": str(job.document_id),
        "document_code": job.document_code,
        "document_title": job.document_title,
        "requested_count": int(job.requested_count or 0),
        "generated_count": int(job.generated_count or 0),
        "approved_count": int(job.approved_count or 0),
        "include_table_questions": bool(job.include_table_questions),
        "status": job.status,
        "generator_model": job.generator_model,
        "prompt_version": job.prompt_version,
        "created_by": job.created_by,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


def serialize_job(job: QAGenerationJob) -> dict[str, object]:
    return _serialize_job(job)


def serialize_draft(draft: QAGeneratedDraft) -> dict[str, object]:
    return {
        "id": str(draft.id),
        "job_id": str(draft.job_id),
        "document_id": str(draft.document_id),
        "document_code": draft.document_code,
        "question": draft.question,
        "answer": draft.answer,
        "short_answer": draft.short_answer,
        "chapter_title": draft.chapter_title,
        "clause_number": draft.clause_number,
        "has_table": bool(draft.has_table),
        "table_id": str(draft.table_id) if draft.table_id else None,
        "table_number": draft.table_number,
        "table_title": draft.table_title,
        "lex_url": draft.lex_url,
        "source_excerpt": draft.source_excerpt,
        "source_anchor": draft.source_anchor,
        "source_kind": draft.source_kind,
        "generation_model": draft.generation_model,
        "prompt_version": draft.prompt_version,
        "status": draft.status,
        "review_note": draft.review_note,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "approved_at": draft.approved_at,
    }
