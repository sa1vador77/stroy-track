"""Аутентификация: вход по email/паролю, профиль владельца токена."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, SessionDep
from app.core.security import authenticate_user, create_access_token
from app.schemas.auth import Token
from app.schemas.users import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    """Вход по email и паролю (поле username формы — это email)."""
    user = await authenticate_user(session, form.username, form.password)
    if user is None:
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
