from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class VerifiedQA(UUIDMixin, Base):
    __tablename__ = "verified_qa"

    normalized_question: Mapped[str] = mapped_column(String(1000), index=True)
    original_question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    short_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_payload: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    verified_by_user: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_count: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
