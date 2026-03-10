from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDMixin


class Section(UUIDMixin, Base):
    __tablename__ = "sections"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    categories = relationship("Category", back_populates="section")
