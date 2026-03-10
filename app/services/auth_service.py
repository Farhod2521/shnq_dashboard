import hashlib
import secrets
import string
import uuid

from sqlalchemy.orm import Session

from app.models.auth_session import AuthSession
from app.models.chat_user import ChatUser

PASSWORD_ALPHABET = string.ascii_lowercase + string.digits


def generate_random_password(length: int = 10) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def hash_password(password: str, salt: str | None = None) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt_value}:{password}".encode("utf-8")).hexdigest()
    return f"{salt_value}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if "$" not in stored_hash:
        return False
    salt, digest = stored_hash.split("$", 1)
    calculated = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(digest, calculated)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        return None
    token = authorization[len(prefix):].strip()
    return token or None


def issue_auth_token(db: Session, user_id: uuid.UUID) -> str:
    token = secrets.token_urlsafe(42)
    db.add(AuthSession(user_id=user_id, token=token))
    db.commit()
    return token


def get_user_by_token(db: Session, token: str | None) -> ChatUser | None:
    if not token:
        return None
    session = db.query(AuthSession).filter(AuthSession.token == token).first()
    if not session:
        return None
    return db.query(ChatUser).filter(ChatUser.id == session.user_id).first()
