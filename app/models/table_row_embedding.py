import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class TableRowEmbedding(UUIDMixin, Base):
    __tablename__ = "table_row_embeddings"

    row_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("norm_table_rows.id", ondelete="CASCADE"), unique=True
    )

    embedding_model: Mapped[str] = mapped_column(String(100))
    vector: Mapped[list] = mapped_column(JSON)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    shnq_code: Mapped[str] = mapped_column(String(100))
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    table_number: Mapped[str] = mapped_column(String(50), index=True)
    table_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    search_text: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    row = relationship("NormTableRow", back_populates="embedding")
