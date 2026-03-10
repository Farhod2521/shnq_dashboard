import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class Category(UUIDMixin, Base):
    __tablename__ = "categories"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))

    section = relationship("Section", back_populates="categories")
    documents = relationship("Document", back_populates="category")

    __table_args__ = (
        UniqueConstraint("section_id", "code", name="uq_section_category_code"),
    )
