import os
import re
import threading
import uuid
from datetime import datetime

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.config import settings
from app.models.chapter import Chapter
from app.models.clause import Clause
from app.models.clause_embedding import ClauseEmbedding
from app.models.document import Document
from app.models.document_process import DocumentProcess
from app.models.image_embedding import ImageEmbedding
from app.models.norm_image import NormImage
from app.models.norm_table import NormTable
from app.models.norm_table_cell import NormTableCell
from app.models.norm_table_row import NormTableRow
from app.models.table_row_embedding import TableRowEmbedding
from app.services.llm_service import embed_text
from app.services.qdrant_service import upsert_clause_embedding
from app.utils.text_fix import repair_mojibake


MIN_TEXT_LEN = 30
PIPELINE_SLOT_SEMAPHORE = threading.BoundedSemaphore(max(1, settings.PIPELINE_MAX_PARALLEL))
TABLE_NUMBER_PATTERNS = [
    re.compile(r"\bjadval\s*[-.]?\s*([0-9]+[a-z]?)\b", re.IGNORECASE),
    re.compile(r"\b([0-9]+[a-z]?)\s*[-.]?\s*jadval\b", re.IGNORECASE),
]
APPENDIX_NUMBER_PATTERN = re.compile(
    r"(?:\b(\d+)\s*[-.]?\s*ilova(?:si|da|ga|dan|ning|lar)?\b|"
    r"\bilova(?:si|da|ga|dan|ning|lar)?\s*[-.]?\s*(\d+)\b)",
    re.IGNORECASE,
)


def clean_text(text: str | None) -> str:
    repaired = repair_mojibake(text or "")
    return re.sub(r"\s+", " ", repaired).strip()


def extract_clause_number(text: str) -> str | None:
    match = re.match(r"^(\d{1,3}(?:\.\d{1,3})*)\s*[\).:-]?\s*", text)
    return match.group(1) if match else None


def extract_doc_code_from_html(soup: BeautifulSoup) -> str | None:
    title_node = soup.find("div", class_=re.compile(r"ACT_TITLE|ACT_TITLE_APPL"))
    title_text = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
    match = re.search(r"\b(SHNQ|QMQ|KMK|SNIP)\s+([0-9][0-9.\-]*)\b", title_text, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"


def _safe_int(value: str | None, default: int = 1) -> int:
    try:
        num = int(value or default)
        return num if num > 0 else default
    except (TypeError, ValueError):
        return default


def _extract_table_number(text: str) -> str | None:
    cleaned = clean_text(text).lower()
    for pattern in TABLE_NUMBER_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return match.group(1)
    return None


def _extract_table_title(text: str) -> str:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    for pattern in TABLE_NUMBER_PATTERNS:
        match = pattern.search(lowered)
        if match:
            start, end = match.span()
            candidate = (cleaned[:start] + cleaned[end:]).strip(" -:.")
            return candidate or cleaned
    return cleaned


def _extract_appendix_number(text: str) -> str | None:
    cleaned = clean_text(text).lower()
    match = APPENDIX_NUMBER_PATTERN.search(cleaned)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _extract_table_label(table_elem) -> str:
    caption = table_elem.find("caption")
    if caption:
        caption_text = clean_text(caption.get_text(" ", strip=True))
        if caption_text:
            return caption_text

    sibling = table_elem
    for _ in range(4):
        sibling = sibling.find_previous_sibling()
        if not sibling:
            break
        sibling_text = clean_text(sibling.get_text(" ", strip=True))
        sibling_classes = {cls.upper() for cls in (sibling.get("class") or [])}
        if sibling_text and (
            "jadval" in sibling_text.lower()
            or _extract_table_number(sibling_text)
            or _extract_appendix_number(sibling_text)
            or "ACT_TITLE_APPL" in sibling_classes
            or any(cls.startswith("APPL_BANNER") for cls in sibling_classes)
        ):
            return sibling_text
    return ""


def _extract_image_context(img_elem) -> str:
    parent_div = img_elem.find_parent("div")
    candidates: list[str] = []

    def add_text(node):
        if not node or node.find("img"):
            return
        text = clean_text(node.get_text(" ", strip=True))
        if not text or text.lower().startswith(("http://", "https://")):
            return
        candidates.append(text[:220])

    if parent_div:
        add_text(parent_div)
        prev = parent_div
        for _ in range(3):
            prev = prev.find_previous_sibling("div")
            if not prev:
                break
            add_text(prev)
        nxt = parent_div
        for _ in range(2):
            nxt = nxt.find_next_sibling("div")
            if not nxt:
                break
            add_text(nxt)

    unique = []
    seen = set()
    for text in candidates:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
        if len(unique) >= 3:
            break
    return " | ".join(unique)


def _escape_md(text: str) -> str:
    return (text or "").replace("|", r"\|")


def _table_to_rows_and_markdown(table_elem):
    parsed_rows = []
    expanded_rows = []
    pending = {}

    for tr in table_elem.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        row_values = []
        row_cells = []
        col_index = 1

        def flush_pending():
            nonlocal col_index
            while col_index in pending:
                text, is_header, remain = pending[col_index]
                row_values.append(text)
                if remain > 1:
                    pending[col_index] = (text, is_header, remain - 1)
                else:
                    pending.pop(col_index, None)
                col_index += 1

        flush_pending()
        for cell in cells:
            flush_pending()
            text = clean_text(cell.get_text(" ", strip=True))
            is_header = cell.name == "th"
            row_span = _safe_int(cell.get("rowspan"), default=1)
            col_span = _safe_int(cell.get("colspan"), default=1)

            row_cells.append(
                {
                    "col_index": col_index,
                    "text": text,
                    "is_header": is_header,
                    "row_span": row_span,
                    "col_span": col_span,
                }
            )

            for offset in range(col_span):
                row_values.append(text)
                if row_span > 1:
                    pending[col_index + offset] = (text, is_header, row_span - 1)
            col_index += col_span

        flush_pending()
        parsed_rows.append(row_cells)
        expanded_rows.append(row_values)

    if not expanded_rows:
        return parsed_rows, ""

    col_count = max(len(row) for row in expanded_rows)
    normalized = [row + [""] * (col_count - len(row)) for row in expanded_rows]
    header = normalized[0]
    sep = ["---"] * col_count
    markdown_lines = [
        "| " + " | ".join(_escape_md(col) for col in header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in normalized[1:]:
        markdown_lines.append("| " + " | ".join(_escape_md(col) for col in row) + " |")

    return parsed_rows, "\n".join(markdown_lines)


def _resolve_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    if os.path.isabs(path_value):
        return path_value
    return os.path.join(os.getcwd(), path_value)


_ERR_UNSET = object()


def _touch_process(
    db: Session,
    process: DocumentProcess,
    *,
    status: str | None = None,
    stage: str | None = None,
    doc_html: int | None = None,
    chunking: int | None = None,
    row_embedding: int | None = None,
    img_embedding: int | None = None,
    error: str | None | object = _ERR_UNSET,
    commit: bool = True,
):
    changed = False
    if status is not None:
        if process.status != status:
            process.status = status
            changed = True
    if stage is not None:
        if process.stage != stage:
            process.stage = stage
            changed = True
    if doc_html is not None:
        next_value = max(0, min(100, doc_html))
        if process.doc_html_progress != next_value:
            process.doc_html_progress = next_value
            changed = True
    if chunking is not None:
        next_value = max(0, min(100, chunking))
        if process.chunking_progress != next_value:
            process.chunking_progress = next_value
            changed = True
    if row_embedding is not None:
        next_value = max(0, min(100, row_embedding))
        if process.row_embedding_progress != next_value:
            process.row_embedding_progress = next_value
            changed = True
    if img_embedding is not None:
        next_value = max(0, min(100, img_embedding))
        if process.img_embedding_progress != next_value:
            process.img_embedding_progress = next_value
            changed = True
    if error is not _ERR_UNSET:
        if process.error_message != error:
            process.error_message = error
            changed = True
    if not changed:
        return
    process.updated_at = datetime.utcnow()
    db.add(process)
    if commit:
        db.commit()
    else:
        db.flush()


def _reset_document_content(db: Session, document_id: uuid.UUID):
    clause_ids = [row[0] for row in db.query(Clause.id).filter(Clause.document_id == document_id).all()]
    table_ids = [row[0] for row in db.query(NormTable.id).filter(NormTable.document_id == document_id).all()]
    row_ids = []
    if table_ids:
        row_ids = [row[0] for row in db.query(NormTableRow.id).filter(NormTableRow.table_id.in_(table_ids)).all()]
    image_ids = [row[0] for row in db.query(NormImage.id).filter(NormImage.document_id == document_id).all()]

    if clause_ids:
        db.query(ClauseEmbedding).filter(ClauseEmbedding.clause_id.in_(clause_ids)).delete(synchronize_session=False)
    if row_ids:
        db.query(TableRowEmbedding).filter(TableRowEmbedding.row_id.in_(row_ids)).delete(synchronize_session=False)
        db.query(NormTableCell).filter(NormTableCell.row_id.in_(row_ids)).delete(synchronize_session=False)
    if image_ids:
        db.query(ImageEmbedding).filter(ImageEmbedding.image_id.in_(image_ids)).delete(synchronize_session=False)

    if row_ids:
        db.query(NormTableRow).filter(NormTableRow.id.in_(row_ids)).delete(synchronize_session=False)
    if table_ids:
        db.query(NormTable).filter(NormTable.id.in_(table_ids)).delete(synchronize_session=False)
    if clause_ids:
        db.query(Clause).filter(Clause.id.in_(clause_ids)).delete(synchronize_session=False)
    if image_ids:
        db.query(NormImage).filter(NormImage.id.in_(image_ids)).delete(synchronize_session=False)

    db.query(Chapter).filter(Chapter.document_id == document_id).delete(synchronize_session=False)
    db.commit()


def _build_row_search_text(row: NormTableRow) -> str:
    table = row.table
    headers: dict[int, str] = {}
    for candidate_row in table.rows:
        for cell in candidate_row.cells:
            text = clean_text(cell.text)
            if text and cell.is_header:
                headers[cell.col_index] = text
        if headers:
            break

    values = []
    for cell in row.cells:
        text = clean_text(cell.text)
        if not text:
            continue
        header = clean_text(headers.get(cell.col_index, ""))
        if header and header.lower() != text.lower():
            values.append(f"{header}: {text}")
        else:
            values.append(f"Ustun {cell.col_index}: {text}")

    if not values:
        return ""

    chapter_title = table.section_title or (table.chapter.title if table.chapter else "")
    lines = [
        f"Hujjat: {table.document.code}",
        f"Jadval: {table.table_number}",
        f"Satr: {row.row_index}",
    ]
    if chapter_title:
        lines.append(f"Bo'lim: {chapter_title}")
    if table.title:
        lines.append(f"Sarlavha: {table.title}")
    lines.append("Qiymatlar: " + " | ".join(values))
    return "\n".join(lines)


def run_document_pipeline(document_id: str):
    acquired = False
    db = None
    # Parallel pipeline sonini global cheklab, DB pool bosimini tushiramiz.
    PIPELINE_SLOT_SEMAPHORE.acquire()
    acquired = True
    db = SessionLocal()
    try:
        doc_id = uuid.UUID(document_id)
        document = db.query(Document).filter(Document.id == doc_id).one_or_none()
        if not document:
            return

        process = db.query(DocumentProcess).filter(DocumentProcess.document_id == doc_id).one_or_none()
        if not process:
            process = DocumentProcess(document_id=doc_id)
            db.add(process)
            db.commit()
            db.refresh(process)

        process.started_at = datetime.utcnow()
        process.finished_at = None
        _touch_process(db, process, status="processing", stage="doc_html", doc_html=0, chunking=0, row_embedding=0, img_embedding=0, error=None)

        _reset_document_content(db, doc_id)

        html_path = _resolve_path(document.html_file)
        if not html_path or not os.path.exists(html_path):
            raise RuntimeError("HTML fayl topilmadi. Avval HTML fayl yuklang.")

        with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
            html_text = repair_mojibake(f.read())
            soup = BeautifulSoup(html_text, "html.parser")

        inferred_code = extract_doc_code_from_html(soup)
        if inferred_code and inferred_code != document.code:
            duplicate = (
                db.query(Document)
                .filter(
                    Document.category_id == document.category_id,
                    Document.code == inferred_code,
                    Document.id != doc_id,
                )
                .one_or_none()
            )
            if duplicate is None:
                document.code = inferred_code
                db.add(document)
                db.commit()

        elements = list(soup.find_all(["div", "a", "table", "img"]))
        total_elements = max(len(elements), 1)

        current_chapter: Chapter | None = None
        chapter_order = 0
        clause_order = 0
        table_order = 0
        table_seq = 0
        image_order = 0
        pending_anchor = None
        last_clause = None
        last_table = None
        last_image = None
        current_appendix_number = None
        current_appendix_title = None
        seen_image_sources = set()

        for idx, elem in enumerate(elements, start=1):
            if elem.name == "a" and elem.get("id"):
                anchor = elem.get("id")
                if elem.find("img"):
                    pending_anchor = anchor
                    continue
                if last_table and not last_table.html_anchor:
                    last_table.html_anchor = anchor
                    db.add(last_table)
                    db.flush()
                elif last_clause and not last_clause.html_anchor:
                    last_clause.html_anchor = anchor
                    db.add(last_clause)
                    db.flush()
                elif last_image and not last_image.html_anchor:
                    last_image.html_anchor = anchor
                    db.add(last_image)
                    db.flush()
                else:
                    pending_anchor = anchor
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            if elem.name == "div" and "TEXT_HEADER_DEFAULT" in (elem.get("class") or []):
                header_text = clean_text(elem.get_text())
                if header_text:
                    chapter_order += 1
                    current_chapter = Chapter(document_id=doc_id, title=header_text, order=chapter_order)
                    db.add(current_chapter)
                    db.flush()
                    current_appendix_number = None
                    current_appendix_title = None
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            elem_classes = {cls.upper() for cls in (elem.get("class") or [])}
            if elem.name == "div" and any(cls.startswith("APPL_BANNER") for cls in elem_classes):
                banner_text = clean_text(elem.get_text(" ", strip=True))
                appendix_number = _extract_appendix_number(banner_text)
                if appendix_number:
                    current_appendix_number = appendix_number
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            if elem.name == "div" and "ACT_TITLE_APPL" in elem_classes:
                current_appendix_title = clean_text(elem.get_text(" ", strip=True)) or None
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            if elem.name == "div" and "ACT_TEXT" in (elem.get("class") or []):
                text = clean_text(elem.get_text())
                if len(text) >= MIN_TEXT_LEN:
                    clause_order += 1
                    last_clause = Clause(
                        document_id=doc_id,
                        chapter_id=current_chapter.id if current_chapter else None,
                        clause_number=extract_clause_number(text),
                        html_anchor=pending_anchor,
                        text=text,
                        order=clause_order,
                    )
                    db.add(last_clause)
                    db.flush()
                    pending_anchor = None
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            if elem.name == "img":
                src = clean_text(elem.get("src") or "")
                if src and src not in seen_image_sources:
                    image_anchor = pending_anchor
                    if not image_anchor:
                        parent_anchor = elem.find_parent("a")
                        if parent_anchor and parent_anchor.get("id"):
                            image_anchor = parent_anchor.get("id")
                    section_title = current_chapter.title if current_chapter else None
                    image_order += 1
                    last_image = NormImage(
                        document_id=doc_id,
                        chapter_id=current_chapter.id if current_chapter else None,
                        section_title=section_title,
                        appendix_number=current_appendix_number,
                        title=current_appendix_title,
                        html_anchor=image_anchor,
                        image_url=src,
                        context_text=_extract_image_context(elem),
                        order=image_order,
                    )
                    db.add(last_image)
                    db.flush()
                    seen_image_sources.add(src)
                pending_anchor = None
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))
                continue

            if elem.name == "table":
                table_label = _extract_table_label(elem)
                table_number = _extract_table_number(table_label or "")
                appendix_number = _extract_appendix_number(table_label or "") or current_appendix_number
                if not table_number and appendix_number:
                    table_number = f"ilova-{appendix_number}"
                if not table_number:
                    table_seq += 1
                    table_number = str(table_seq)
                table_title = _extract_table_title(table_label) if table_label else None
                rows, markdown = _table_to_rows_and_markdown(elem)
                if rows:
                    table_order += 1
                    section_title = current_chapter.title if current_chapter else None
                    last_table = NormTable(
                        document_id=doc_id,
                        chapter_id=current_chapter.id if current_chapter else None,
                        section_title=section_title,
                        table_number=table_number,
                        title=table_title,
                        html_anchor=pending_anchor,
                        raw_html=str(elem),
                        markdown=markdown,
                        order=table_order,
                    )
                    db.add(last_table)
                    db.flush()
                    pending_anchor = None
                    for row_idx, row_cells in enumerate(rows, start=1):
                        row_obj = NormTableRow(table_id=last_table.id, row_index=row_idx)
                        db.add(row_obj)
                        db.flush()
                        for cell in row_cells:
                            db.add(
                                NormTableCell(
                                    row_id=row_obj.id,
                                    col_index=cell["col_index"],
                                    text=cell["text"],
                                    is_header=cell["is_header"],
                                    row_span=cell["row_span"],
                                    col_span=cell["col_span"],
                                )
                            )
                        db.flush()
                _touch_process(db, process, doc_html=round((idx / total_elements) * 100))

        _touch_process(db, process, stage="chunking", chunking=0)
        clauses = db.query(Clause).filter(Clause.document_id == doc_id).order_by(Clause.order).all()
        total_clauses = max(len(clauses), 1)
        for idx, clause in enumerate(clauses, start=1):
            _ = [chunk for chunk in re.split(r"(?<=[.!?])\s+", clause.text) if chunk]
            _touch_process(db, process, chunking=round((idx / total_clauses) * 100))

        _touch_process(db, process, stage="row_embedding", row_embedding=0)
        table_rows = (
            db.query(NormTableRow)
            .join(NormTable, NormTableRow.table_id == NormTable.id)
            .filter(NormTable.document_id == doc_id)
            .order_by(NormTable.order, NormTableRow.row_index)
            .all()
        )
        total_rows = max(len(table_rows), 1)
        for idx, row in enumerate(table_rows, start=1):
            search_text = _build_row_search_text(row)
            if search_text:
                vector = embed_text(search_text)
                existing = db.query(TableRowEmbedding).filter(TableRowEmbedding.row_id == row.id).one_or_none()
                chapter_title = row.table.section_title or (row.table.chapter.title if row.table.chapter else None)
                if existing:
                    existing.embedding_model = settings.EMBEDDING_MODEL
                    existing.vector = vector
                    existing.token_count = len(search_text.split())
                    existing.shnq_code = document.code
                    existing.chapter_title = chapter_title
                    existing.table_number = row.table.table_number
                    existing.table_title = row.table.title
                    existing.row_index = row.row_index
                    existing.search_text = search_text
                    db.add(existing)
                else:
                    db.add(
                        TableRowEmbedding(
                            row_id=row.id,
                            embedding_model=settings.EMBEDDING_MODEL,
                            vector=vector,
                            token_count=len(search_text.split()),
                            shnq_code=document.code,
                            chapter_title=chapter_title,
                            table_number=row.table.table_number,
                            table_title=row.table.title,
                            row_index=row.row_index,
                            search_text=search_text,
                        )
                    )
            _touch_process(
                db,
                process,
                row_embedding=round((idx / total_rows) * 100),
                commit=False,
            )
            # Embedding navbatida connectionni uzoq ushlab turmaslik uchun
            # har iteratsiyada transactionni yakunlaymiz.
            db.commit()

        _touch_process(db, process, stage="img_embedding", img_embedding=0)
        images = db.query(NormImage).filter(NormImage.document_id == doc_id).order_by(NormImage.order).all()
        total_images = max(len(images), 1)
        for idx, image in enumerate(images, start=1):
            parts = [f"Hujjat: {document.code}", f"Rasm URL: {image.image_url}"]
            if image.section_title:
                parts.append(f"Bo'lim: {image.section_title}")
            if image.appendix_number:
                parts.append(f"Ilova: {image.appendix_number}")
            if image.title:
                parts.append(f"Sarlavha: {image.title}")
            if image.context_text:
                parts.append(f"Kontekst: {image.context_text}")
            text_for_embedding = "\n".join(parts)
            vector = embed_text(text_for_embedding)
            existing = db.query(ImageEmbedding).filter(ImageEmbedding.image_id == image.id).one_or_none()
            chapter_title = image.section_title or (image.chapter.title if image.chapter else None)
            if existing:
                existing.embedding_model = settings.EMBEDDING_MODEL
                existing.vector = vector
                existing.token_count = len(text_for_embedding.split())
                existing.shnq_code = document.code
                existing.chapter_title = chapter_title
                existing.appendix_number = image.appendix_number
                existing.image_url = image.image_url
                db.add(existing)
            else:
                db.add(
                    ImageEmbedding(
                        image_id=image.id,
                        embedding_model=settings.EMBEDDING_MODEL,
                        vector=vector,
                        token_count=len(text_for_embedding.split()),
                        shnq_code=document.code,
                        chapter_title=chapter_title,
                        appendix_number=image.appendix_number,
                        image_url=image.image_url,
                    )
                )
            _touch_process(
                db,
                process,
                img_embedding=round((idx / total_images) * 100),
                commit=False,
            )
            # Uzoq davom etadigan bosqichlarda pool bo'sh turishi uchun
            # har iteratsiyada commit qilamiz.
            db.commit()

        process.finished_at = datetime.utcnow()
        _touch_process(
            db,
            process,
            status="done",
            stage="done",
            doc_html=100,
            chunking=100,
            row_embedding=100,
            img_embedding=100,
            error=None,
        )

        # Qo'shimcha bosqich: clause embeddinglar (chat sifati uchun).
        # UI stage-lari yakunlangach done holatiga o'tkazib, bu bosqichni fonda davom ettiramiz.
        try:
            for idx, clause in enumerate(clauses, start=1):
                vector = embed_text(clause.text)
                existing = db.query(ClauseEmbedding).filter(ClauseEmbedding.clause_id == clause.id).one_or_none()
                chapter_title = clause.chapter.title if clause.chapter else None
                if existing:
                    existing.embedding_model = settings.EMBEDDING_MODEL
                    existing.vector = vector
                    existing.token_count = len(clause.text.split())
                    existing.shnq_code = document.code
                    existing.chapter_title = chapter_title
                    existing.clause_number = clause.clause_number
                    existing.lex_url = document.lex_url
                    db.add(existing)
                else:
                    db.add(
                        ClauseEmbedding(
                            clause_id=clause.id,
                            embedding_model=settings.EMBEDDING_MODEL,
                            vector=vector,
                            token_count=len(clause.text.split()),
                            shnq_code=document.code,
                            chapter_title=chapter_title,
                            clause_number=clause.clause_number,
                            lex_url=document.lex_url,
                        )
                    )
                # DB transactionni tez yakunlab, connectionni poolga qaytaramiz.
                db.commit()
                upsert_clause_embedding(
                    clause_id=str(clause.id),
                    vector=vector,
                    shnq_code=document.code,
                    clause_number=clause.clause_number,
                    chapter_title=chapter_title,
                    document_id=str(clause.document_id) if clause.document_id else None,
                    section_id=str(clause.chapter_id) if clause.chapter_id else None,
                    page=None,
                    language="uz",
                    content_type="clause",
                )
        except Exception:
            db.rollback()
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        doc_process = None
        try:
            parsed_id = uuid.UUID(document_id)
            doc_process = db.query(DocumentProcess).filter(DocumentProcess.document_id == parsed_id).one_or_none()
        except Exception:
            doc_process = None
        if doc_process:
            try:
                _touch_process(
                    db,
                    doc_process,
                    status="failed",
                    stage="failed",
                    error=str(exc),
                )
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
        print(f"[pipeline] document_id={document_id} failed: {exc}")
    finally:
        if db is not None:
            db.close()
        if acquired:
            PIPELINE_SLOT_SEMAPHORE.release()
