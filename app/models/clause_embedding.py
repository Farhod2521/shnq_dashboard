import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class ClauseEmbedding(UUIDMixin, Base):
    __tablename__ = "clause_embeddings"

    clause_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clauses.id", ondelete="CASCADE"), unique=True
    )

    embedding_model: Mapped[str] = mapped_column(String(100))
    vector: Mapped[list] = mapped_column(JSON)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    shnq_code: Mapped[str] = mapped_column(String(100))
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    clause_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lex_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    clause = relationship("Clause", back_populates="embedding")
