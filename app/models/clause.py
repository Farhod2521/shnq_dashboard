import uuid
from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class Clause(UUIDMixin, Base):
    __tablename__ = "clauses"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"),
        nullable=True
    )
    clause_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    html_anchor: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)

    document = relationship("Document", back_populates="clauses")
    chapter = relationship("Chapter", back_populates="clauses")
    embedding = relationship("ClauseEmbedding", back_populates="clause", uselist=False)
