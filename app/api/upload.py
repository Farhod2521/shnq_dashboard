import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.dependency import get_db
from app.db.session import SessionLocal
from app.models.category import Category
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
from app.models.section import Section
from app.models.table_row_embedding import TableRowEmbedding
from app.services.ingestion_service import run_document_pipeline


router = APIRouter()

UPLOAD_BASE = os.path.join(os.getcwd(), "uploads")
ORIGINAL_DIR = os.path.join(UPLOAD_BASE, "docs", "original")
HTML_DIR = os.path.join(UPLOAD_BASE, "docs", "html")

QUEUE_POLL_SECONDS = 3
QUEUE_BATCH_LIMIT = 32

_PIPELINE_WORKER_LOCK = threading.Lock()
_PIPELINE_WORKER_STARTED = False
_PIPELINE_WAKE_EVENT = threading.Event()


class DocumentStageProgress(BaseModel):
    docHtml: int
    chunking: int
    rowEmbedding: int
    imgEmbedding: int


class SectionListItem(BaseModel):
    id: str
    code: str
    name: str


class SectionCreateRequest(BaseModel):
    code: str
    name: str | None = None


class CategoryListItem(BaseModel):
    id: str
    sectionId: str
    sectionCode: str
    sectionName: str
    code: str
    name: str


class CategoryCreateRequest(BaseModel):
    sectionId: str
    code: str
    name: str | None = None


class DocumentListItem(BaseModel):
    id: str
    code: str
    title: str
    categoryId: str | None = None
    category: str
    categoryName: str | None = None
    section: str | None = None
    lexUrl: str | None = None
    status: str
    progress: DocumentStageProgress
    failedAt: str | None = None
    errorMessage: str | None = None
    createdAt: datetime


class DocumentCreateResponse(BaseModel):
    id: str
    code: str
    status: str


class DocumentRequeueResponse(BaseModel):
    detail: str
    queuedCount: int
    documentIds: list[str]


class DeleteResponse(BaseModel):
    detail: str


class DocumentStatusResponse(BaseModel):
    id: str
    status: str
    stage: str
    progress: DocumentStageProgress
    errorMessage: str | None = None


class DashboardStatsResponse(BaseModel):
    totalDocuments: int
    queuedDocuments: int
    processingDocuments: int
    doneDocuments: int
    failedDocuments: int
    totalClauses: int
    totalTables: int
    totalTableRows: int
    clauseEmbeddings: int
    tableRowEmbeddings: int
    imageEmbeddings: int
    embeddingCoveragePercent: int


class DocumentEmbeddingSummary(BaseModel):
    total: int
    clause: int
    tableRow: int
    image: int


class DocumentEmbeddingItem(BaseModel):
    id: str
    type: str
    sequenceNumber: int
    referenceNumber: str
    name: str
    chapterTitle: str | None = None
    tokenCount: int
    embeddingModel: str
    preview: str | None = None
    createdAt: datetime
    normTable: dict[str, str] | None = None


class DocumentEmbeddingListResponse(BaseModel):
    documentId: str
    code: str
    title: str
    summary: DocumentEmbeddingSummary
    items: list[DocumentEmbeddingItem]


def _ensure_dirs():
    os.makedirs(ORIGINAL_DIR, exist_ok=True)
    os.makedirs(HTML_DIR, exist_ok=True)


def _save_upload(target_dir: str, file: UploadFile | None) -> str | None:
    if file is None:
        return None
    ext = os.path.splitext(file.filename or "")[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    abs_path = os.path.join(target_dir, filename)
    with open(abs_path, "wb") as f:
        f.write(file.file.read())
    return os.path.relpath(abs_path, os.getcwd()).replace("\\", "/")


def _delete_upload_file(path_value: str | None):
    if not path_value:
        return
    abs_path = os.path.abspath(os.path.join(os.getcwd(), path_value))
    if not abs_path.startswith(os.path.abspath(os.getcwd())):
        return
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def _map_stage_to_failed_at(stage: str) -> str | None:
    if stage == "doc_html":
        return "docHtml"
    if stage == "chunking":
        return "chunking"
    if stage == "row_embedding":
        return "rowEmbedding"
    if stage == "img_embedding":
        return "imgEmbedding"
    return None


def _preview_text(value: str | None, limit: int = 220) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _normalize_code(value: str, field_name: str) -> str:
    cleaned = (value or "").strip().upper()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name} bo'sh bo'lmasligi kerak.")
    return cleaned


def _parse_uuid_or_400(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Noto'g'ri {field_name}.") from exc


def _ensure_default_section(db: Session) -> Section:
    section = db.query(Section).filter(Section.code == "UMUMIY").one_or_none()
    if section:
        return section
    section = Section(code="UMUMIY", name="Umumiy")
    db.add(section)
    db.flush()
    return section


def _resolve_category(
    db: Session,
    category_id: str | None,
    category_code: str | None,
) -> Category:
    if category_id:
        parsed_id = _parse_uuid_or_400(category_id, "category_id")
        cat = (
            db.query(Category)
            .options(joinedload(Category.section))
            .filter(Category.id == parsed_id)
            .one_or_none()
        )
        if not cat:
            raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")
        return cat

    normalized_code = _normalize_code(category_code or "", "Kategoriya kodi")
    cat = (
        db.query(Category)
        .options(joinedload(Category.section))
        .filter(Category.code == normalized_code)
        .order_by(Category.name.asc())
        .first()
    )
    if cat:
        return cat

    section = _ensure_default_section(db)
    cat = Category(section_id=section.id, code=normalized_code, name=normalized_code)
    db.add(cat)
    db.flush()
    return cat


def _to_section_item(section: Section) -> SectionListItem:
    return SectionListItem(id=str(section.id), code=section.code, name=section.name)


def _to_category_item(category: Category) -> CategoryListItem:
    section = category.section
    return CategoryListItem(
        id=str(category.id),
        sectionId=str(category.section_id),
        sectionCode=section.code if section else "",
        sectionName=section.name if section else "",
        code=category.code,
        name=category.name,
    )


def _set_process_queued(db: Session, document_id: uuid.UUID):
    process = db.query(DocumentProcess).filter(DocumentProcess.document_id == document_id).one_or_none()
    if not process:
        process = DocumentProcess(document_id=document_id)
    process.status = "queued"
    process.stage = "queued"
    process.doc_html_progress = 0
    process.chunking_progress = 0
    process.row_embedding_progress = 0
    process.img_embedding_progress = 0
    process.error_message = None
    process.started_at = None
    process.finished_at = None
    process.updated_at = datetime.utcnow()
    db.add(process)


def _resolve_parallel_workers(document_ids: list[str], max_parallel: int | None = None) -> int:
    if not document_ids:
        return 0
    requested = settings.PIPELINE_MAX_PARALLEL if max_parallel is None else max_parallel
    if requested <= 0:
        return len(document_ids)
    return max(1, min(requested, len(document_ids)))


def _run_pipeline_batch(document_ids: list[str], max_parallel: int | None = None):
    if not document_ids:
        return

    worker_count = _resolve_parallel_workers(document_ids, max_parallel=max_parallel)
    if worker_count <= 1:
        for document_id in document_ids:
            try:
                run_document_pipeline(document_id)
            except Exception:
                # Individual pipeline xatoligi DocumentProcess status=failed ga tushadi.
                continue
        return

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="doc-pipeline") as executor:
        futures = [executor.submit(run_document_pipeline, document_id) for document_id in document_ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                # Individual pipeline xatoligi qolgan ishlarni to'xtatmasin.
                continue


def _wake_pipeline_worker():
    _PIPELINE_WAKE_EVENT.set()


def _ensure_process_rows_for_missing_documents(db: Session, *, limit: int) -> int:
    missing_docs = _collect_documents_without_process(db, limit=limit)
    if not missing_docs:
        return 0
    for doc in missing_docs:
        _set_process_queued(db, doc.id)
    db.commit()
    return len(missing_docs)


def _recover_stale_processing_rows(db: Session, *, stale_after_minutes: int = 15, limit: int = 500) -> int:
    threshold = datetime.utcnow() - timedelta(minutes=max(1, stale_after_minutes))
    rows = (
        db.query(DocumentProcess)
        .filter(DocumentProcess.status == "processing", DocumentProcess.updated_at < threshold)
        .order_by(DocumentProcess.updated_at.asc())
        .limit(limit)
        .all()
    )
    if not rows:
        return 0

    now = datetime.utcnow()
    for row in rows:
        row.status = "queued"
        row.stage = "queued"
        row.updated_at = now
        db.add(row)
    db.commit()
    return len(rows)


def _claim_queued_document_ids(*, limit: int) -> list[str]:
    db = SessionLocal()
    try:
        _ensure_process_rows_for_missing_documents(db, limit=max(limit, QUEUE_BATCH_LIMIT))
        rows = (
            db.query(DocumentProcess)
            .filter(DocumentProcess.status == "queued")
            .order_by(DocumentProcess.updated_at.asc())
            .limit(limit)
            .all()
        )
        if not rows:
            return []

        now = datetime.utcnow()
        out: list[str] = []
        for row in rows:
            row.status = "processing"
            if not row.stage:
                row.stage = "queued"
            row.updated_at = now
            db.add(row)
            out.append(str(row.document_id))
        db.commit()
        return out
    finally:
        db.close()


def _pipeline_worker_loop():
    while True:
        try:
            batch_size = max(1, min(max(1, settings.PIPELINE_MAX_PARALLEL), QUEUE_BATCH_LIMIT))
            document_ids = _claim_queued_document_ids(limit=batch_size)
            if document_ids:
                _run_pipeline_batch(document_ids, max_parallel=settings.PIPELINE_MAX_PARALLEL)
                continue
        except Exception as exc:  # noqa: BLE001
            print(f"[pipeline-worker] error: {exc}")
        _PIPELINE_WAKE_EVENT.wait(timeout=QUEUE_POLL_SECONDS)
        _PIPELINE_WAKE_EVENT.clear()


def start_document_pipeline_worker(
    *,
    recover_failed: bool = False,
    stale_after_minutes: int = 15,
    recover_limit: int = 2000,
) -> int:
    global _PIPELINE_WORKER_STARTED
    with _PIPELINE_WORKER_LOCK:
        if not _PIPELINE_WORKER_STARTED:
            thread = threading.Thread(
                target=_pipeline_worker_loop,
                daemon=True,
                name="document-pipeline-worker",
            )
            thread.start()
            _PIPELINE_WORKER_STARTED = True

    db = SessionLocal()
    try:
        _recover_stale_processing_rows(
            db,
            stale_after_minutes=stale_after_minutes,
            limit=recover_limit,
        )
        if recover_failed:
            failed_rows = (
                db.query(DocumentProcess)
                .filter(DocumentProcess.status == "failed")
                .order_by(DocumentProcess.updated_at.asc())
                .limit(recover_limit)
                .all()
            )
            for row in failed_rows:
                row.status = "queued"
                row.stage = "queued"
                row.updated_at = datetime.utcnow()
                db.add(row)
            if failed_rows:
                db.commit()
        _ensure_process_rows_for_missing_documents(db, limit=recover_limit)

        pending_process = (
            db.query(func.count(DocumentProcess.id))
            .filter(DocumentProcess.status.in_(["queued", "processing"]))
            .scalar()
            or 0
        )
        missing_process = (
            db.query(func.count(Document.id))
            .filter(~Document.id.in_(db.query(DocumentProcess.document_id)))
            .scalar()
            or 0
        )
    finally:
        db.close()

    _wake_pipeline_worker()
    return int(pending_process + missing_process)


def _collect_requeue_targets(
    db: Session,
    *,
    include_failed: bool = False,
    include_done: bool = False,
    limit: int = 500,
) -> list[DocumentProcess]:
    statuses = ["queued", "processing"]
    if include_failed:
        statuses.append("failed")
    if include_done:
        statuses.append("done")
    return (
        db.query(DocumentProcess)
        .filter(DocumentProcess.status.in_(statuses))
        .order_by(DocumentProcess.updated_at.asc())
        .limit(limit)
        .all()
    )


def _collect_documents_without_process(db: Session, *, limit: int = 500) -> list[Document]:
    if limit <= 0:
        return []
    process_doc_ids = db.query(DocumentProcess.document_id)
    return (
        db.query(Document)
        .filter(~Document.id.in_(process_doc_ids))
        .order_by(Document.created_at.asc())
        .limit(limit)
        .all()
    )


def _requeue_process_rows(db: Session, process_rows: list[DocumentProcess]) -> list[str]:
    if not process_rows:
        return []
    for row in process_rows:
        _set_process_queued(db, row.document_id)
    db.commit()
    return [str(row.document_id) for row in process_rows]


def _purge_document_relations(db: Session, document_id: uuid.UUID):
    clause_ids = [row[0] for row in db.query(Clause.id).filter(Clause.document_id == document_id).all()]
    table_ids = [row[0] for row in db.query(NormTable.id).filter(NormTable.document_id == document_id).all()]
    image_ids = [row[0] for row in db.query(NormImage.id).filter(NormImage.document_id == document_id).all()]
    row_ids: list[uuid.UUID] = []
    if table_ids:
        row_ids = [row[0] for row in db.query(NormTableRow.id).filter(NormTableRow.table_id.in_(table_ids)).all()]

    if clause_ids:
        db.query(ClauseEmbedding).filter(ClauseEmbedding.clause_id.in_(clause_ids)).delete(synchronize_session=False)
    if row_ids:
        db.query(TableRowEmbedding).filter(TableRowEmbedding.row_id.in_(row_ids)).delete(synchronize_session=False)
        db.query(NormTableCell).filter(NormTableCell.row_id.in_(row_ids)).delete(synchronize_session=False)
        db.query(NormTableRow).filter(NormTableRow.id.in_(row_ids)).delete(synchronize_session=False)
    if image_ids:
        db.query(ImageEmbedding).filter(ImageEmbedding.image_id.in_(image_ids)).delete(synchronize_session=False)
        db.query(NormImage).filter(NormImage.id.in_(image_ids)).delete(synchronize_session=False)
    if table_ids:
        db.query(NormTable).filter(NormTable.id.in_(table_ids)).delete(synchronize_session=False)
    if clause_ids:
        db.query(Clause).filter(Clause.id.in_(clause_ids)).delete(synchronize_session=False)

    db.query(Chapter).filter(Chapter.document_id == document_id).delete(synchronize_session=False)
    db.query(DocumentProcess).filter(DocumentProcess.document_id == document_id).delete(synchronize_session=False)


def resume_document_pipelines_on_startup(
    *,
    include_failed: bool = False,
    limit: int = 500,
    max_parallel: int | None = None,
) -> int:
    _ = max_parallel  # backward compatibility
    return start_document_pipeline_worker(
        recover_failed=include_failed,
        stale_after_minutes=15,
        recover_limit=max(1, limit),
    )


def _to_list_item(document: Document, process: DocumentProcess | None) -> DocumentListItem:
    status = process.status if process else "queued"
    stage = process.stage if process else "queued"
    doc_html = process.doc_html_progress if process else 0
    chunking = process.chunking_progress if process else 0
    row_embedding = process.row_embedding_progress if process else 0
    img_embedding = process.img_embedding_progress if process else 0

    if status == "processing" and doc_html == 100 and chunking == 100 and row_embedding == 100 and img_embedding == 100:
        status = "done"
        stage = "done"

    error_message = process.error_message if process else None
    if status == "done":
        error_message = None
    return DocumentListItem(
        id=str(document.id),
        code=document.code,
        title=document.title,
        categoryId=str(document.category_id) if document.category_id else None,
        category=document.category.code if document.category else "UMUMIY",
        categoryName=document.category.name if document.category else "Umumiy",
        section=document.category.section.code if document.category and document.category.section else None,
        lexUrl=document.lex_url,
        status=status,
        progress=DocumentStageProgress(
            docHtml=doc_html,
            chunking=chunking,
            rowEmbedding=row_embedding,
            imgEmbedding=img_embedding,
        ),
        failedAt=_map_stage_to_failed_at(stage) if status == "failed" else None,
        errorMessage=error_message,
        createdAt=document.created_at,
    )


@router.get("/sections", response_model=list[SectionListItem])
def list_sections(db: Session = Depends(get_db)):
    sections = db.query(Section).order_by(Section.code.asc()).all()
    return [_to_section_item(section) for section in sections]


@router.post("/sections", response_model=SectionListItem)
def create_section(payload: SectionCreateRequest, db: Session = Depends(get_db)):
    code = _normalize_code(payload.code, "Bo'lim kodi")
    name = (payload.name or "").strip() or code

    exists = db.query(Section).filter(Section.code == code).one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Bu bo'lim kodi allaqachon mavjud.")

    section = Section(code=code, name=name)
    db.add(section)
    db.commit()
    db.refresh(section)
    return _to_section_item(section)


@router.put("/sections/{section_id}", response_model=SectionListItem)
def update_section(section_id: str, payload: SectionCreateRequest, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(section_id, "section_id")
    section = db.query(Section).filter(Section.id == parsed_id).one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Bo'lim topilmadi.")

    code = _normalize_code(payload.code, "Bo'lim kodi")
    name = (payload.name or "").strip() or code

    conflict = db.query(Section).filter(Section.code == code, Section.id != parsed_id).one_or_none()
    if conflict:
        raise HTTPException(status_code=409, detail="Bu bo'lim kodi allaqachon mavjud.")

    section.code = code
    section.name = name
    db.commit()
    db.refresh(section)
    return _to_section_item(section)


@router.delete("/sections/{section_id}", response_model=DeleteResponse)
def delete_section(section_id: str, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(section_id, "section_id")
    section = db.query(Section).filter(Section.id == parsed_id).one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Bo'lim topilmadi.")

    category_count = db.query(func.count(Category.id)).filter(Category.section_id == parsed_id).scalar() or 0
    if category_count > 0:
        raise HTTPException(status_code=409, detail="Bu bo'limga bog'langan kategoriyalar mavjud.")

    db.delete(section)
    db.commit()
    return DeleteResponse(detail="Bo'lim o'chirildi.")


@router.get("/categories", response_model=list[CategoryListItem])
def list_categories(section_id: str | None = Query(default=None), db: Session = Depends(get_db)):
    query = (
        db.query(Category)
        .options(joinedload(Category.section))
        .order_by(Category.code.asc(), Category.name.asc())
    )
    if section_id:
        parsed = _parse_uuid_or_400(section_id, "section_id")
        query = query.filter(Category.section_id == parsed)

    categories = query.all()
    return [_to_category_item(category) for category in categories]


@router.post("/categories", response_model=CategoryListItem)
def create_category(payload: CategoryCreateRequest, db: Session = Depends(get_db)):
    parsed_section_id = _parse_uuid_or_400(payload.sectionId, "section_id")
    section = db.query(Section).filter(Section.id == parsed_section_id).one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Bo'lim topilmadi.")

    code = _normalize_code(payload.code, "Kategoriya kodi")
    name = (payload.name or "").strip() or code

    exists = (
        db.query(Category)
        .filter(Category.section_id == section.id, Category.code == code)
        .one_or_none()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Bu bo'limda bunday kategoriya kodi mavjud.")

    category = Category(section_id=section.id, code=code, name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return _to_category_item(category)


@router.put("/categories/{category_id}", response_model=CategoryListItem)
def update_category(category_id: str, payload: CategoryCreateRequest, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(category_id, "category_id")
    category = db.query(Category).options(joinedload(Category.section)).filter(Category.id == parsed_id).one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")

    parsed_section_id = _parse_uuid_or_400(payload.sectionId, "section_id")
    section = db.query(Section).filter(Section.id == parsed_section_id).one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Bo'lim topilmadi.")

    code = _normalize_code(payload.code, "Kategoriya kodi")
    name = (payload.name or "").strip() or code

    conflict = (
        db.query(Category)
        .filter(
            Category.section_id == parsed_section_id,
            Category.code == code,
            Category.id != parsed_id,
        )
        .one_or_none()
    )
    if conflict:
        raise HTTPException(status_code=409, detail="Bu bo'limda bunday kategoriya kodi mavjud.")

    category.section_id = parsed_section_id
    category.code = code
    category.name = name
    db.commit()
    db.refresh(category)
    return _to_category_item(category)


@router.delete("/categories/{category_id}", response_model=DeleteResponse)
def delete_category(category_id: str, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(category_id, "category_id")
    category = db.query(Category).filter(Category.id == parsed_id).one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Kategoriya topilmadi.")

    document_count = db.query(func.count(Document.id)).filter(Document.category_id == parsed_id).scalar() or 0
    if document_count > 0:
        raise HTTPException(status_code=409, detail="Bu kategoriyaga bog'langan hujjatlar mavjud.")

    db.delete(category)
    db.commit()
    return DeleteResponse(detail="Kategoriya o'chirildi.")


@router.post("/documents", response_model=DocumentCreateResponse)
def create_document(
    background_tasks: BackgroundTasks,
    category_id: str | None = Form(default=None),
    category: str | None = Form(default=None),
    title: str = Form(...),
    code: str = Form(...),
    lex_url: str | None = Form(default=None),
    original_file: UploadFile | None = File(default=None),
    html_file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    if not html_file:
        raise HTTPException(status_code=400, detail="HTML fayl majburiy.")

    _ensure_dirs()
    original_path = _save_upload(ORIGINAL_DIR, original_file)
    html_path = _save_upload(HTML_DIR, html_file)

    cat = _resolve_category(db=db, category_id=category_id, category_code=category)

    doc = (
        db.query(Document)
        .filter(Document.category_id == cat.id, Document.code == code.strip())
        .one_or_none()
    )
    if doc:
        doc.title = title.strip()
        doc.lex_url = (lex_url or "").strip() or None
        doc.original_file = original_path or doc.original_file
        doc.html_file = html_path
    else:
        doc = Document(
            category_id=cat.id,
            title=title.strip(),
            code=code.strip(),
            lex_url=(lex_url or "").strip() or None,
            original_file=original_path,
            html_file=html_path,
        )
        db.add(doc)
    db.commit()
    db.refresh(doc)

    _set_process_queued(db, doc.id)
    db.commit()

    _wake_pipeline_worker()

    return DocumentCreateResponse(id=str(doc.id), code=doc.code, status="queued")


@router.put("/documents/{document_id}", response_model=DocumentCreateResponse)
def update_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    category_id: str | None = Form(default=None),
    category: str | None = Form(default=None),
    title: str = Form(...),
    code: str = Form(...),
    lex_url: str | None = Form(default=None),
    original_file: UploadFile | None = File(default=None),
    html_file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    parsed_id = _parse_uuid_or_400(document_id, "document_id")
    doc = db.query(Document).filter(Document.id == parsed_id).one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")

    cat = _resolve_category(db=db, category_id=category_id, category_code=category)

    cleaned_code = (code or "").strip()
    cleaned_title = (title or "").strip()
    if not cleaned_code:
        raise HTTPException(status_code=400, detail="Hujjat kodi bo'sh bo'lmasligi kerak.")
    if not cleaned_title:
        raise HTTPException(status_code=400, detail="Hujjat sarlavhasi bo'sh bo'lmasligi kerak.")

    conflict = (
        db.query(Document)
        .filter(
            Document.category_id == cat.id,
            Document.code == cleaned_code,
            Document.id != parsed_id,
        )
        .one_or_none()
    )
    if conflict:
        raise HTTPException(status_code=409, detail="Bu kategoriyada bunday hujjat kodi mavjud.")

    original_path = None
    html_path = None
    if original_file is not None or html_file is not None:
        _ensure_dirs()
        original_path = _save_upload(ORIGINAL_DIR, original_file)
        html_path = _save_upload(HTML_DIR, html_file)

    code_changed = doc.code != cleaned_code
    html_changed = html_path is not None
    original_changed = original_path is not None

    old_original = doc.original_file
    old_html = doc.html_file

    doc.category_id = cat.id
    doc.title = cleaned_title
    doc.code = cleaned_code
    doc.lex_url = (lex_url or "").strip() or None
    if original_path is not None:
        doc.original_file = original_path
    if html_path is not None:
        doc.html_file = html_path
    db.add(doc)

    should_reprocess = code_changed or html_changed or original_changed
    status = "updated"
    if should_reprocess:
        _set_process_queued(db, doc.id)
        status = "queued"

    db.commit()
    db.refresh(doc)

    if original_path and old_original and old_original != original_path:
        _delete_upload_file(old_original)
    if html_path and old_html and old_html != html_path:
        _delete_upload_file(old_html)

    if should_reprocess:
        _wake_pipeline_worker()

    return DocumentCreateResponse(id=str(doc.id), code=doc.code, status=status)


@router.post("/documents/requeue-stuck", response_model=DocumentRequeueResponse)
def requeue_stuck_documents(
    background_tasks: BackgroundTasks,
    include_failed: bool = Query(default=False),
    include_done: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=5000),
    max_parallel: int = Query(default=0, ge=0, le=128),
    db: Session = Depends(get_db),
):
    process_rows = _collect_requeue_targets(
        db,
        include_failed=include_failed,
        include_done=include_done,
        limit=limit,
    )
    document_ids = _requeue_process_rows(db, process_rows)

    remaining = max(0, limit - len(document_ids))
    if remaining > 0:
        missing_docs = _collect_documents_without_process(db, limit=remaining)
        for doc in missing_docs:
            _set_process_queued(db, doc.id)
            document_ids.append(str(doc.id))
        if missing_docs:
            db.commit()

    if not document_ids:
        return DocumentRequeueResponse(
            detail="Qayta navbatga qo'yiladigan hujjat topilmadi.",
            queuedCount=0,
            documentIds=[],
        )

    _ = max_parallel  # worker settings orqali boshqariladi
    _wake_pipeline_worker()
    return DocumentRequeueResponse(
        detail="Hujjatlar qayta navbatga qo'yildi va pipeline ishga tushirildi.",
        queuedCount=len(document_ids),
        documentIds=document_ids,
    )


@router.delete("/documents/{document_id}", response_model=DeleteResponse)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(document_id, "document_id")
    doc = db.query(Document).filter(Document.id == parsed_id).one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")

    original_path = doc.original_file
    html_path = doc.html_file

    _purge_document_relations(db, parsed_id)
    db.delete(doc)
    db.commit()

    _delete_upload_file(original_path)
    _delete_upload_file(html_path)

    return DeleteResponse(detail="Hujjat o'chirildi.")


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(db: Session = Depends(get_db)):
    docs = (
        db.query(Document)
        .options(joinedload(Document.category).joinedload(Category.section))
        .order_by(Document.created_at.desc())
        .all()
    )
    if not docs:
        return []

    process_rows = (
        db.query(DocumentProcess)
        .filter(DocumentProcess.document_id.in_([doc.id for doc in docs]))
        .all()
    )
    process_by_doc_id = {row.document_id: row for row in process_rows}

    result: list[DocumentListItem] = []
    for doc in docs:
        result.append(_to_list_item(doc, process_by_doc_id.get(doc.id)))
    return result


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
def document_status(document_id: str, db: Session = Depends(get_db)):
    try:
        parsed = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Noto'g'ri document id.") from exc

    process = db.query(DocumentProcess).filter(DocumentProcess.document_id == parsed).one_or_none()
    if not process:
        raise HTTPException(status_code=404, detail="Jarayon topilmadi.")

    status_value = process.status
    stage_value = process.stage
    if (
        status_value == "processing"
        and process.doc_html_progress == 100
        and process.chunking_progress == 100
        and process.row_embedding_progress == 100
        and process.img_embedding_progress == 100
    ):
        status_value = "done"
        stage_value = "done"

    return DocumentStatusResponse(
        id=document_id,
        status=status_value,
        stage=stage_value,
        progress=DocumentStageProgress(
            docHtml=process.doc_html_progress,
            chunking=process.chunking_progress,
            rowEmbedding=process.row_embedding_progress,
            imgEmbedding=process.img_embedding_progress,
        ),
        errorMessage=None if status_value == "done" else process.error_message,
    )


@router.get("/dashboard-stats", response_model=DashboardStatsResponse)
def dashboard_stats(db: Session = Depends(get_db)):
    total_documents = db.query(func.count(Document.id)).scalar() or 0

    processes = db.query(DocumentProcess).all()
    queued = 0
    processing = 0
    done = 0
    failed = 0
    for process in processes:
        status_value = process.status or "queued"
        if (
            status_value == "processing"
            and process.doc_html_progress == 100
            and process.chunking_progress == 100
            and process.row_embedding_progress == 100
            and process.img_embedding_progress == 100
        ):
            status_value = "done"
        if status_value == "queued":
            queued += 1
        elif status_value == "processing":
            processing += 1
        elif status_value == "done":
            done += 1
        elif status_value == "failed":
            failed += 1

    # Process yozuvi hali yaratilmagan hujjatlar bo'lsa, ularni navbatdagiga qo'shamiz.
    missing_process = max(total_documents - len(processes), 0)
    queued += missing_process

    total_clauses = db.query(func.count(Clause.id)).scalar() or 0
    total_tables = db.query(func.count(NormTable.id)).scalar() or 0
    total_table_rows = db.query(func.count(NormTableRow.id)).scalar() or 0
    clause_embeddings = db.query(func.count(ClauseEmbedding.id)).scalar() or 0
    table_row_embeddings = db.query(func.count(TableRowEmbedding.id)).scalar() or 0
    image_embeddings = db.query(func.count(ImageEmbedding.id)).scalar() or 0

    coverage = 0
    if total_table_rows > 0:
        coverage = int(round((table_row_embeddings / total_table_rows) * 100))
    coverage = max(0, min(100, coverage))

    return DashboardStatsResponse(
        totalDocuments=total_documents,
        queuedDocuments=queued,
        processingDocuments=processing,
        doneDocuments=done,
        failedDocuments=failed,
        totalClauses=total_clauses,
        totalTables=total_tables,
        totalTableRows=total_table_rows,
        clauseEmbeddings=clause_embeddings,
        tableRowEmbeddings=table_row_embeddings,
        imageEmbeddings=image_embeddings,
        embeddingCoveragePercent=coverage,
    )


@router.get("/documents/{document_id}/embeddings", response_model=DocumentEmbeddingListResponse)
def list_document_embeddings(
    document_id: str,
    kind: str = Query(default="all", pattern="^(all|clause|table_row|image)$"),
    limit: int = Query(default=1000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        parsed = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Noto'g'ri document id.") from exc

    document = db.query(Document).filter(Document.id == parsed).one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi.")

    clause_count = (
        db.query(func.count(ClauseEmbedding.id))
        .join(Clause, ClauseEmbedding.clause_id == Clause.id)
        .filter(Clause.document_id == parsed)
        .scalar()
        or 0
    )
    table_row_count = (
        db.query(func.count(TableRowEmbedding.id))
        .join(NormTableRow, TableRowEmbedding.row_id == NormTableRow.id)
        .join(NormTable, NormTableRow.table_id == NormTable.id)
        .filter(NormTable.document_id == parsed)
        .scalar()
        or 0
    )
    image_count = (
        db.query(func.count(ImageEmbedding.id))
        .join(NormImage, ImageEmbedding.image_id == NormImage.id)
        .filter(NormImage.document_id == parsed)
        .scalar()
        or 0
    )

    merged_items: list[tuple[int, int, DocumentEmbeddingItem]] = []

    if kind in {"all", "clause"}:
        clause_rows = (
            db.query(ClauseEmbedding, Clause)
            .join(Clause, ClauseEmbedding.clause_id == Clause.id)
            .filter(Clause.document_id == parsed)
            .order_by(Clause.order.asc())
            .all()
        )
        for emb, clause in clause_rows:
            sequence = clause.order or 0
            reference = emb.clause_number or str(sequence or "-")
            name = f"Band {reference}"
            merged_items.append(
                (
                    0,
                    sequence,
                    DocumentEmbeddingItem(
                        id=str(emb.id),
                        type="clause",
                        sequenceNumber=sequence,
                        referenceNumber=reference,
                        name=name,
                        chapterTitle=emb.chapter_title,
                        tokenCount=emb.token_count,
                        embeddingModel=emb.embedding_model,
                        preview=_preview_text(clause.text),
                        createdAt=emb.created_at,
                    ),
                )
            )

    if kind in {"all", "table_row"}:
        row_items = (
            db.query(TableRowEmbedding, NormTableRow, NormTable)
            .join(NormTableRow, TableRowEmbedding.row_id == NormTableRow.id)
            .join(NormTable, NormTableRow.table_id == NormTable.id)
            .filter(NormTable.document_id == parsed)
            .order_by(NormTable.order.asc(), NormTableRow.row_index.asc())
            .all()
        )
        for emb, row, table in row_items:
            sequence = row.row_index or 0
            reference = f"{emb.table_number}:{sequence}"
            if emb.table_title:
                name = f"Jadval {emb.table_number} - {emb.table_title} (qator {sequence})"
            else:
                name = f"Jadval {emb.table_number} (qator {sequence})"
            merged_items.append(
                (
                    1,
                    (table.order or 0) * 100000 + sequence,
                    DocumentEmbeddingItem(
                        id=str(emb.id),
                        type="table_row",
                        sequenceNumber=sequence,
                        referenceNumber=reference,
                        name=name,
                        chapterTitle=emb.chapter_title,
                        tokenCount=emb.token_count,
                        embeddingModel=emb.embedding_model,
                        preview=_preview_text(emb.search_text),
                        createdAt=emb.created_at,
                        normTable={
                            "rawHtml": table.raw_html or "",
                            "rawHtmlRu": table.raw_html_ru or "",
                            "rawHtmlEn": table.raw_html_en or "",
                            "rawHtmlKo": table.raw_html_ko or "",
                            "markdown": table.markdown or "",
                            "markdownRu": table.markdown_ru or "",
                            "markdownEn": table.markdown_en or "",
                            "markdownKo": table.markdown_ko or "",
                        },
                    ),
                )
            )

    if kind in {"all", "image"}:
        image_items = (
            db.query(ImageEmbedding, NormImage)
            .join(NormImage, ImageEmbedding.image_id == NormImage.id)
            .filter(NormImage.document_id == parsed)
            .order_by(NormImage.order.asc())
            .all()
        )
        for emb, image in image_items:
            sequence = image.order or 0
            reference = emb.appendix_number or str(sequence or "-")
            name = f"Rasm {reference}"
            merged_items.append(
                (
                    2,
                    sequence,
                    DocumentEmbeddingItem(
                        id=str(emb.id),
                        type="image",
                        sequenceNumber=sequence,
                        referenceNumber=reference,
                        name=name,
                        chapterTitle=emb.chapter_title,
                        tokenCount=emb.token_count,
                        embeddingModel=emb.embedding_model,
                        preview=_preview_text(emb.image_url),
                        createdAt=emb.created_at,
                    ),
                )
            )

    merged_items.sort(key=lambda row: (row[0], row[1]))
    paged = [item for _, _, item in merged_items[offset : offset + limit]]

    return DocumentEmbeddingListResponse(
        documentId=document_id,
        code=document.code,
        title=document.title,
        summary=DocumentEmbeddingSummary(
            total=clause_count + table_row_count + image_count,
            clause=clause_count,
            tableRow=table_row_count,
            image=image_count,
        ),
        items=paged,
    )
