from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    active_shnq = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)