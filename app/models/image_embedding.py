import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class ImageEmbedding(UUIDMixin, Base):
    __tablename__ = "image_embeddings"

    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("norm_images.id", ondelete="CASCADE"), unique=True
    )

    embedding_model: Mapped[str] = mapped_column(String(100))
    vector: Mapped[list] = mapped_column(JSON)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    shnq_code: Mapped[str] = mapped_column(String(100))
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    appendix_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    image_url: Mapped[str] = mapped_column(String(1000))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    image = relationship("NormImage", back_populates="embedding")
