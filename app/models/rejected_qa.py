from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class RejectedQA(UUIDMixin, Base):
    __tablename__ = "rejected_qa"

    normalized_question: Mapped[str] = mapped_column(String(1000), index=True)
    original_question: Mapped[str] = mapped_column(Text)
    rejected_answer: Mapped[str] = mapped_column(Text)
    rejected_source_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rejected_source_payload: Mapped[list | None] = mapped_column(JSON, nullable=True)
    document_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rejected_count: Mapped[int] = mapped_column(Integer, default=1)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
