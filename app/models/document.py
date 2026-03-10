import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class Document(UUIDMixin, Base):
    __tablename__ = "documents"

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(500))
    code: Mapped[str] = mapped_column(String(100), index=True)
    lex_url: Mapped[str | None] = mapped_column(String, nullable=True)
    original_file: Mapped[str | None] = mapped_column(String, nullable=True)
    html_file: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    category = relationship("Category", back_populates="documents")
    chapters = relationship("Chapter", back_populates="document")
    clauses = relationship("Clause", back_populates="document")
    tables = relationship("NormTable", back_populates="document")
    images = relationship("NormImage", back_populates="document")
    process = relationship("DocumentProcess", back_populates="document", uselist=False)

    __table_args__ = (
        UniqueConstraint("category_id", "code", name="uq_category_code"),
    )
