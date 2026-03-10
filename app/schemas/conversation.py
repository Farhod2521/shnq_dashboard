from pydantic import BaseModel
from datetime import datetime


class ConversationCreate(BaseModel):
    active_shnq: str | None = None


class ConversationResponse(BaseModel):
    id: int
    active_shnq: str | None
    created_at: datetime

    class Config:
        from_attributes = True