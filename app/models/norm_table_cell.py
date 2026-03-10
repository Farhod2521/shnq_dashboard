import uuid
from sqlalchemy import Integer, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin


class NormTableCell(UUIDMixin, Base):
    __tablename__ = "norm_table_cells"

    row_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("norm_table_rows.id", ondelete="CASCADE"))
    col_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    is_header: Mapped[bool] = mapped_column(Boolean, default=False)
    row_span: Mapped[int] = mapped_column(Integer, default=1)
    col_span: Mapped[int] = mapped_column(Integer, default=1)

    row = relationship("NormTableRow", back_populates="cells")

    __table_args__ = (
        UniqueConstraint("row_id", "col_index", name="uq_row_col_index"),
    )
