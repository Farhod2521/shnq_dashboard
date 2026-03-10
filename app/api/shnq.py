from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependency import get_db
from app.models.conversation import Conversation
from app.schemas.conversation import ConversationCreate, ConversationResponse

router = APIRouter()


@router.post("/", response_model=ConversationResponse)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db)
):
    conversation = Conversation(active_shnq=data.active_shnq)

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation