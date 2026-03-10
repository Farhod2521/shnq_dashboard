import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class NormTable(UUIDMixin, Base):
    __tablename__ = "norm_tables"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )

    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    table_number: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    html_anchor: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    raw_html: Mapped[str] = mapped_column(Text, default="")
    raw_html_ru: Mapped[str] = mapped_column(Text, default="")
    raw_html_en: Mapped[str] = mapped_column(Text, default="")
    raw_html_ko: Mapped[str] = mapped_column(Text, default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    markdown_ru: Mapped[str] = mapped_column(Text, default="")
    markdown_en: Mapped[str] = mapped_column(Text, default="")
    markdown_ko: Mapped[str] = mapped_column(Text, default="")

    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="tables")
    chapter = relationship("Chapter", back_populates="tables")
    rows = relationship("NormTableRow", back_populates="table")
