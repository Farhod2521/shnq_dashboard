import uuid
from sqlalchemy import String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class Chapter(UUIDMixin, Base):
    __tablename__ = "chapters"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    order: Mapped[int] = mapped_column(Integer, default=0)

    document = relationship("Document", back_populates="chapters")
    clauses = relationship("Clause", back_populates="chapter")
    tables = relationship("NormTable", back_populates="chapter")
    images = relationship("NormImage", back_populates="chapter")
