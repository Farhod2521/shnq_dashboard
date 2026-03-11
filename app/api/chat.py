from datetime import datetime
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependency import get_db
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.chat_user import ChatUser
from app.services.auth_service import extract_bearer_token, get_user_by_token
from app.services.chat_service import answer_message


router = APIRouter()
DOCUMENT_CODE_RE = re.compile(r"\b(shnq|qmq|kmk|snip)\s*([0-9][0-9.\-]*)\b", re.IGNORECASE)
AMBIGUOUS_DOCUMENT_PROMPT = "savolda bir nechta hujjatda mos variant topildi"
GUEST_LIMIT_ERROR_CODE = "guest_limit_reached"


class ChatPingRequest(BaseModel):
    message: str = "ping"


class ChatMessageRequest(BaseModel):
    message: str
    document_code: str | None = None
    session_id: str | None = None
    room_id: str | None = None


class ChatSessionCreateRequest(BaseModel):
    room_id: str | None = None
    title: str | None = None


class ChatSessionResponse(BaseModel):
    id: str
    title: str | None = None
    room_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageHistoryItem(BaseModel):
    id: str
    role: str
    content: str
    sources: list | None = None
    table_html: str | None = None
    image_urls: list | None = None
    created_at: datetime


class ChatMessageHistoryResponse(BaseModel):
    session: ChatSessionResponse
    messages: list[ChatMessageHistoryItem]


class QAHistoryItem(BaseModel):
    id: str
    session_id: str
    room_id: str | None = None
    asked_by: str
    email: str | None = None
    phone: str | None = None
    question: str
    answer: str | None = None
    asked_at: datetime
    answered_at: datetime | None = None


def _normalize_room_id(room_id: str | None) -> str | None:
    if room_id is None:
        return None
    room_id_value = room_id.strip()
    if not room_id_value:
        return None
    try:
        return str(uuid.UUID(room_id_value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="room_id UUID formatda bo'lishi kerak.") from exc


def _normalize_session_id(session_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="session_id UUID formatda bo'lishi kerak.") from exc


def _extract_answer_text(data: dict) -> str:
    return (
        str(data.get("answer") or "")
        or str(data.get("response") or "")
        or str(data.get("message") or "")
        or str(data.get("output") or "")
    )


def _short_title(message: str) -> str:
    compact = " ".join((message or "").strip().split())
    if len(compact) <= 80:
        return compact
    return f"{compact[:77]}..."


def _extract_document_codes(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in DOCUMENT_CODE_RE.finditer(" ".join((text or "").split())):
        code = f"{match.group(1).upper()} {match.group(2)}"
        key = code.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(code)
    return out


def _normalize_document_code(value: str | None) -> str | None:
    if not value:
        return None
    codes = _extract_document_codes(value)
    if codes:
        return codes[0]
    compact = " ".join(value.split())
    return compact or None


def _looks_like_document_selection(message: str) -> bool:
    text = " ".join((message or "").strip().split())
    if not text:
        return False
    if not _extract_document_codes(text):
        return False
    token_count = len(text.split())
    if token_count <= 8:
        return True
    lowered = text.lower()
    selection_markers = ("shu", "tanla", "tanladim", "kerak", "mana")
    return token_count <= 14 and any(marker in lowered for marker in selection_markers)


def _resolve_followup_document_request(
    db: Session,
    session: ChatSession | None,
    user_message: str,
    document_code: str | None,
) -> tuple[str, str | None, dict | None]:
    effective_message = user_message
    effective_document_code = _normalize_document_code(document_code)

    if not session:
        return effective_message, effective_document_code, None

    selected_from_message = _normalize_document_code(user_message)
    selected_code = effective_document_code or selected_from_message
    if not selected_code:
        return effective_message, effective_document_code, None
    compact_user_message = " ".join((user_message or "").strip().split())
    short_document_reply = bool(effective_document_code) and len(compact_user_message.split()) <= 6
    if not _looks_like_document_selection(user_message) and not short_document_reply:
        return effective_message, effective_document_code, None

    last_assistant = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if not last_assistant:
        return effective_message, effective_document_code, None
    if AMBIGUOUS_DOCUMENT_PROMPT not in (last_assistant.content or "").lower():
        return effective_message, effective_document_code, None

    candidate_codes = _extract_document_codes(last_assistant.content or "")
    if candidate_codes and selected_code.lower() not in {code.lower() for code in candidate_codes}:
        return effective_message, effective_document_code, None

    previous_user = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "user",
            ChatMessage.created_at < last_assistant.created_at,
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if not previous_user or not (previous_user.content or "").strip():
        return effective_message, effective_document_code, None

    return (
        previous_user.content.strip(),
        selected_code,
        {
            "followup_mode": "document_selection",
            "followup_selected_document": selected_code,
            "followup_original_question": previous_user.content.strip(),
        },
    )


def _to_session_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=str(session.id),
        title=session.title,
        room_id=session.guest_room_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _to_message_response(message: ChatMessage) -> ChatMessageHistoryItem:
    return ChatMessageHistoryItem(
        id=str(message.id),
        role=message.role,
        content=message.content,
        sources=message.sources,
        table_html=message.table_html,
        image_urls=message.image_urls,
        created_at=message.created_at,
    )


def _get_optional_user(db: Session, authorization: str | None) -> ChatUser | None:
    token = extract_bearer_token(authorization)
    return get_user_by_token(db, token)


def _check_session_access(
    session: ChatSession | None,
    user: ChatUser | None,
    room_id: str | None,
) -> None:
    if not session:
        raise HTTPException(status_code=404, detail="Session topilmadi.")
    if user and str(session.user_id) == str(user.id):
        return
    if not user and session.user_id is None and session.guest_room_id == room_id:
        return
    raise HTTPException(status_code=403, detail="Ushbu sessiyaga ruxsat yo'q.")


def _count_guest_questions(db: Session, room_id: str) -> int:
    count = (
        db.query(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .filter(
            ChatSession.user_id.is_(None),
            ChatSession.guest_room_id == room_id,
            ChatMessage.role == "user",
        )
        .scalar()
    )
    return int(count or 0)


def _raise_guest_limit(limit: int) -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "code": GUEST_LIMIT_ERROR_CODE,
            "message": f"Mehmon sifatida {limit} ta savoldan keyin tizimga kirish talab qilinadi.",
            "limit": limit,
        },
    )


@router.post("/ping")
def chat_ping(payload: ChatPingRequest):
    return {"reply": payload.message}


@router.get("/ping")
def chat_ping_get():
    return {"reply": "pong"}


@router.get("/qa-history", response_model=list[QAHistoryItem])
def list_qa_history(
    limit: int = Query(default=300, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChatMessage, ChatSession, ChatUser)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .outerjoin(ChatUser, ChatSession.user_id == ChatUser.id)
        .order_by(ChatSession.id.asc(), ChatMessage.created_at.asc())
        .all()
    )

    pending_by_session: dict[uuid.UUID, list[dict]] = {}
    qa_items: list[dict] = []

    for message, session, user in rows:
        if message.role == "user":
            full_name = ""
            if user:
                full_name = " ".join([user.first_name or "", user.last_name or ""]).strip()
            asked_by = full_name or (user.email if user and user.email else "Mehmon")
            pending_by_session.setdefault(session.id, []).append(
                {
                    "id": str(message.id),
                    "session_id": str(session.id),
                    "room_id": session.guest_room_id,
                    "asked_by": asked_by,
                    "email": user.email if user else None,
                    "phone": user.phone if user else None,
                    "question": message.content,
                    "answer": None,
                    "asked_at": message.created_at,
                    "answered_at": None,
                }
            )
            continue

        if message.role == "assistant":
            queue = pending_by_session.get(session.id) or []
            if not queue:
                continue
            item = queue.pop(0)
            item["answer"] = message.content
            item["answered_at"] = message.created_at
            qa_items.append(item)

    for pending_items in pending_by_session.values():
        qa_items.extend(pending_items)

    qa_items.sort(key=lambda item: item["asked_at"], reverse=True)
    sliced = qa_items[:limit]
    return [QAHistoryItem(**item) for item in sliced]


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    room_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _get_optional_user(db, authorization)
    normalized_room = _normalize_room_id(room_id)

    query = db.query(ChatSession)
    if user:
        sessions = (
            query.filter(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        return [_to_session_response(item) for item in sessions]

    if not normalized_room:
        return []

    sessions = (
        query.filter(ChatSession.user_id.is_(None), ChatSession.guest_room_id == normalized_room)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [_to_session_response(item) for item in sessions]


@router.post("/sessions", response_model=ChatSessionResponse)
def create_session(
    payload: ChatSessionCreateRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _get_optional_user(db, authorization)
    normalized_room = _normalize_room_id(payload.room_id)
    title = payload.title.strip() if payload.title else None

    if user:
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        db.commit()
        db.refresh(session)
        return _to_session_response(session)

    room_value = normalized_room or str(uuid.uuid4())
    session = (
        db.query(ChatSession)
        .filter(ChatSession.user_id.is_(None), ChatSession.guest_room_id == room_value)
        .first()
    )
    if not session:
        session = ChatSession(guest_room_id=room_value, title=title)
        db.add(session)
        db.commit()
        db.refresh(session)
    return _to_session_response(session)


@router.get("/sessions/{session_id}/messages", response_model=ChatMessageHistoryResponse)
def get_session_messages(
    session_id: str,
    room_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _get_optional_user(db, authorization)
    normalized_room = _normalize_room_id(room_id)
    normalized_session = _normalize_session_id(session_id)

    session = db.query(ChatSession).filter(ChatSession.id == normalized_session).first()
    _check_session_access(session=session, user=user, room_id=normalized_room)

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return ChatMessageHistoryResponse(
        session=_to_session_response(session),
        messages=[_to_message_response(item) for item in messages],
    )


@router.post("/")
def chat_message(
    payload: ChatMessageRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    normalized_room = _normalize_room_id(payload.room_id)
    user = _get_optional_user(db, authorization)

    try:
        session: ChatSession | None = None
        if payload.session_id:
            normalized_session = _normalize_session_id(payload.session_id)
            session = db.query(ChatSession).filter(ChatSession.id == normalized_session).first()
            _check_session_access(session=session, user=user, room_id=normalized_room)
        elif user:
            session = ChatSession(user_id=user.id, title=_short_title(payload.message))
            db.add(session)
            db.commit()
            db.refresh(session)
        else:
            room_value = normalized_room or str(uuid.uuid4())
            session = (
                db.query(ChatSession)
                .filter(ChatSession.user_id.is_(None), ChatSession.guest_room_id == room_value)
                .first()
            )
            if not session:
                session = ChatSession(guest_room_id=room_value, title=_short_title(payload.message))
                db.add(session)
                db.commit()
                db.refresh(session)

        if not user:
            limit = max(1, int(settings.CHAT_GUEST_MESSAGE_LIMIT))
            guest_room = session.guest_room_id if session else None
            if guest_room and _count_guest_questions(db, guest_room) >= limit:
                _raise_guest_limit(limit)

        effective_message, effective_document_code, followup_meta = _resolve_followup_document_request(
            db=db,
            session=session,
            user_message=payload.message,
            document_code=payload.document_code,
        )

        result = answer_message(
            db=db,
            message=effective_message,
            document_code=effective_document_code,
        )
        if followup_meta:
            if not isinstance(result.get("meta"), dict):
                result["meta"] = {}
            result["meta"].update(followup_meta)

        assistant_text = _extract_answer_text(result)
        if not session.title:
            session.title = _short_title(payload.message)

        user_message = ChatMessage(
            session_id=session.id,
            role="user",
            content=payload.message.strip(),
            sources=None,
            table_html=None,
            image_urls=None,
        )
        assistant_message = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=assistant_text,
            sources=result.get("sources") if isinstance(result.get("sources"), list) else None,
            table_html=result.get("table_html"),
            image_urls=result.get("image_urls") if isinstance(result.get("image_urls"), list) else None,
        )
        session.updated_at = datetime.utcnow()
        db.add(user_message)
        db.add(assistant_message)
        db.add(session)
        db.commit()

        result["session_id"] = str(session.id)
        result["room_id"] = session.guest_room_id
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Chat xatoligi: {exc}") from exc
