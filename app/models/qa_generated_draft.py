from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class QAGeneratedDraft(UUIDMixin, Base):
    __tablename__ = "qa_generated_drafts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qa_generation_jobs.id", ondelete="CASCADE"),
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    document_code: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    short_answer: Mapped[str] = mapped_column(Text)
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    clause_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    has_table: Mapped[bool] = mapped_column(Boolean, default=False)
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("norm_tables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    table_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    table_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lex_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text)
    source_anchor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="clause")
    generation_model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
