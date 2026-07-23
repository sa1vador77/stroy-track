"""Парольная политика и JWT: argon2-хэши, выпуск и разбор токенов."""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.concurrency import run_in_threadpool
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User

ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


# фиктивный хэш для login: время ответа не должно зависеть от того, найден ли пользователь
DUMMY_PASSWORD_HASH = _password_hash.hash("dummy-password")


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    """Активный пользователь по email/паролю, иначе None — без причины отказа.

    Единая точка входа по паролю для JSON-API и веб-формы дашборда:
    timing-safe логика не дублируется и не расходится."""
    # email хранится в нижнем регистре — вход не зависит от регистра ввода
    user = await session.scalar(select(User).where(User.email == email.lower()))
    # argon2 — CPU-bound, поэтому тредпул; хэш проверяем и для неизвестного email,
    # чтобы по времени ответа нельзя было перебирать зарегистрированные адреса
    known_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    password_ok = await run_in_threadpool(verify_password, password, known_hash)
    if user is None or user.password_hash is None or not password_ok or not user.is_active:
        return None
    return user


def create_access_token(user_id: int, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    if expires_minutes is None:
        expires_minutes = settings.access_token_expire_minutes
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int:
    """Возвращает user_id из токена; бросает jwt.InvalidTokenError."""
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    try:
        return int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise jwt.InvalidTokenError("invalid sub claim") from exc
