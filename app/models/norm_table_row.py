import uuid
from sqlalchemy import Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class NormTableRow(UUIDMixin, Base):
    __tablename__ = "norm_table_rows"

    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("norm_tables.id", ondelete="CASCADE"))
    row_index: Mapped[int] = mapped_column(Integer)

    table = relationship("NormTable", back_populates="rows")
    cells = relationship("NormTableCell", back_populates="row")
    embedding = relationship("TableRowEmbedding", back_populates="row", uselist=False)

    __table_args__ = (
        UniqueConstraint("table_id", "row_index", name="uq_table_row_index"),
    )
