from datetime import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.dependency import get_db
from app.models.auth_session import AuthSession
from app.models.chat_session import ChatSession
from app.models.chat_user import ChatUser
from app.services.auth_service import (
    extract_bearer_token,
    generate_random_password,
    get_user_by_token,
    hash_password,
    issue_auth_token,
    verify_password,
)

router = APIRouter()


class UserOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    login: str
    created_at: datetime


class RegisterRequest(BaseModel):
    first_name: Annotated[str, Field(min_length=2, max_length=120)]
    last_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: Annotated[str, Field(min_length=5, max_length=255)]
    phone: Annotated[str, Field(min_length=7, max_length=32)]


class RegisterResponse(BaseModel):
    token: str
    generated_password: str
    user: UserOut


class LoginRequest(BaseModel):
    login: Annotated[str, Field(min_length=3, max_length=64)]
    password: Annotated[str, Field(min_length=3, max_length=128)]


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class DeleteResponse(BaseModel):
    detail: str


def _to_user_out(user: ChatUser) -> UserOut:
    return UserOut(
        id=str(user.id),
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone=user.phone,
        login=user.login,
        created_at=user.created_at,
    )


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")


def _parse_uuid_or_400(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Noto'g'ri {field_name}.") from exc


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    normalized_phone = _normalize_phone(payload.phone)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="Telefon raqami noto'g'ri.")

    email_value = payload.email.strip().lower()
    if "@" not in email_value:
        raise HTTPException(status_code=400, detail="Email noto'g'ri formatda.")
    existing = (
        db.query(ChatUser)
        .filter(
            (ChatUser.email == email_value)
            | (ChatUser.phone == normalized_phone)
            | (ChatUser.login == normalized_phone)
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ushbu email yoki telefon bilan akkaunt allaqachon mavjud.",
        )

    generated_password = generate_random_password()
    user = ChatUser(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=email_value,
        phone=normalized_phone,
        login=normalized_phone,
        password_hash=hash_password(generated_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = issue_auth_token(db, user.id)
    return RegisterResponse(
        token=token,
        generated_password=generated_password,
        user=_to_user_out(user),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    login_value = payload.login.strip()
    user = db.query(ChatUser).filter(ChatUser.login == login_value).first()
    if not user:
        user = db.query(ChatUser).filter(ChatUser.phone == _normalize_phone(login_value)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login yoki parol noto'g'ri.",
        )

    token = issue_auth_token(db, user.id)
    return LoginResponse(token=token, user=_to_user_out(user))


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    users = db.query(ChatUser).order_by(ChatUser.created_at.desc()).all()
    return [_to_user_out(user) for user in users]


@router.delete("/users/{user_id}", response_model=DeleteResponse)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    parsed_id = _parse_uuid_or_400(user_id, "user_id")
    user = db.query(ChatUser).filter(ChatUser.id == parsed_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi.")

    db.query(ChatSession).filter(ChatSession.user_id == parsed_id).update(
        {ChatSession.user_id: None},
        synchronize_session=False,
    )
    db.query(AuthSession).filter(AuthSession.user_id == parsed_id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return DeleteResponse(detail="Foydalanuvchi o'chirildi.")


@router.get("/me", response_model=UserOut)
def me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    token = extract_bearer_token(authorization)
    user = get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Autorizatsiya talab qilinadi.")
    return _to_user_out(user)


@router.post("/logout")
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    token = extract_bearer_token(authorization)
    if not token:
        return {"ok": True}
    db.query(AuthSession).filter(AuthSession.token == token).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}
