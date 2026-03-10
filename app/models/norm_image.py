import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class NormImage(UUIDMixin, Base):
    __tablename__ = "norm_images"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )

    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    appendix_number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    html_anchor: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    image_url: Mapped[str] = mapped_column(String(1000))
    local_path: Mapped[str] = mapped_column(String(500), default="")
    context_text: Mapped[str] = mapped_column(Text, default="")
    ocr_text: Mapped[str] = mapped_column(Text, default="")

    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="images")
    chapter = relationship("Chapter", back_populates="images")
    embedding = relationship("ImageEmbedding", back_populates="image", uselist=False)
