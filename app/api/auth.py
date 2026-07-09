from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.models import User
from app.schemas.auth import Token
from app.schemas.users import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    """Вход по email и паролю (поле username формы — это email)."""
    user = await session.scalar(select(User).where(User.email == form.username))
    # argon2 — CPU-bound, поэтому тредпул; хэш проверяем и для неизвестного email,
    # чтобы по времени ответа нельзя было перебирать зарегистрированные адреса
    known_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    password_ok = await run_in_threadpool(verify_password, form.password, known_hash)
    if user is None or user.password_hash is None or not password_ok or not user.is_active:
        # один ответ на все случаи, чтобы не раскрывать, какой email зарегистрирован
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    """Профиль владельца токена."""
    return UserOut.model_validate(user)
