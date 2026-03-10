from datetime import datetime
from sqlalchemy import Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDMixin


class QuestionAnswer(UUIDMixin, Base):
    __tablename__ = "question_answers"

    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    top_clause_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
