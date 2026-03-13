import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.dependency import get_db
from app.models.qa_generation_job import QAGenerationJob
from app.services.qa_generator_service import (
    approve_draft,
    cancel_generation_job,
    create_generation_job,
    delete_generation_job,
    extend_generation_job,
    get_document_generator_context,
    get_table_preview,
    list_drafts,
    list_jobs,
    reject_draft,
    restart_generation_job,
    run_generation_job,
    search_documents_for_generator,
    serialize_draft,
    serialize_job,
)


router = APIRouter()


class DocumentSearchItem(BaseModel):
    id: str
    code: str
    title: str
    lex_url: str | None = None
    clause_count: int
    table_count: int
    approved_count: int


class GeneratorContextResponse(BaseModel):
    id: str
    code: str
    title: str
    lex_url: str | None = None
    category: str | None = None
    clause_count: int
    table_count: int
    approved_count: int
    latest_job: dict | None = None


class GenerationJobCreateRequest(BaseModel):
    document_id: str
    requested_count: int = Field(ge=1, le=100)
    include_table_questions: bool = True
    created_by: str | None = None


class ReviewRequest(BaseModel):
    review_note: str | None = None


class BulkApproveRequest(BaseModel):
    draft_ids: list[str]
    review_note: str | None = None


class ExtendJobRequest(BaseModel):
    additional_count: int = Field(ge=1, le=100)


@router.get("/documents", response_model=list[DocumentSearchItem])
def search_documents(
    q: str = Query(default="", alias="query"),
    limit: int = Query(default=15, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return search_documents_for_generator(db, q, limit=limit)


@router.get("/documents/{document_id}/context", response_model=GeneratorContextResponse)
def get_document_context(document_id: str, db: Session = Depends(get_db)):
    try:
        uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="document_id noto'g'ri.") from exc
    try:
        return get_document_generator_context(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs")
def start_generation_job(
    payload: GenerationJobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        job = create_generation_job(
            db,
            document_id=payload.document_id,
            requested_count=payload.requested_count,
            include_table_questions=payload.include_table_questions,
            created_by=payload.created_by,
        )
        db.commit()
        db.refresh(job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(run_generation_job, str(job.id))
    return {"job": serialize_job(job)}


@router.get("/jobs")
def get_jobs(
    document_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    try:
        jobs = list_jobs(db, document_id=document_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [serialize_job(job) for job in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="job_id noto'g'ri.") from exc
    job = db.query(QAGenerationJob).filter(QAGenerationJob.id == job_uuid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job topilmadi.")
    return {"job": serialize_job(job)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    try:
        job = cancel_generation_job(db, job_id)
        db.commit()
        db.refresh(job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "job": serialize_job(job)}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    try:
        delete_generation_job(db, job_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/jobs/{job_id}/restart")
def restart_job(job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        job = restart_generation_job(db, job_id)
        db.commit()
        db.refresh(job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_generation_job, str(job.id))
    return {"ok": True, "job": serialize_job(job)}


@router.post("/jobs/{job_id}/extend")
def extend_job(
    job_id: str,
    payload: ExtendJobRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        job = extend_generation_job(db, job_id, payload.additional_count)
        db.commit()
        db.refresh(job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_generation_job, str(job.id))
    return {"ok": True, "job": serialize_job(job)}


@router.get("/drafts")
def get_drafts(
    document_id: str | None = Query(default=None),
    job_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    try:
        drafts = list_drafts(db, document_id=document_id, job_id=job_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [serialize_draft(draft) for draft in drafts]}


@router.post("/drafts/{draft_id}/approve")
def approve_generated_draft(draft_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    try:
        row = approve_draft(db, draft_id, review_note=payload.review_note)
        db.commit()
        db.refresh(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "verified_qa_id": str(row.id)}


@router.post("/drafts/bulk-approve")
def bulk_approve_generated_drafts(payload: BulkApproveRequest, db: Session = Depends(get_db)):
    approved_ids: list[str] = []
    for raw_id in payload.draft_ids:
        try:
            row = approve_draft(db, raw_id, review_note=payload.review_note)
            approved_ids.append(str(row.id))
        except ValueError:
            continue
    db.commit()
    return {"ok": True, "approved_count": len(approved_ids), "verified_qa_ids": approved_ids}


@router.post("/drafts/{draft_id}/reject")
def reject_generated_draft(draft_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    try:
        deleted_id = reject_draft(db, draft_id, review_note=payload.review_note)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted_draft_id": deleted_id}


@router.get("/tables/{table_id}")
def preview_table(table_id: str, db: Session = Depends(get_db)):
    try:
        return get_table_preview(db, table_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
