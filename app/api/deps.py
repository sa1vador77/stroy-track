"""Зависимости эндпоинтов: сессия БД, текущий пользователь, проверка ролей."""

from collections.abc import Callable, Coroutine
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import User, UserRole
from app.models.base import PG_INT_MAX

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# id в путях ограничены диапазоном PG INTEGER: выход за него — 422 на валидации,
# а не DataError из драйвера посреди запроса
PathID = Annotated[int, Path(ge=1, le=PG_INT_MAX)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    """Пользователь по Bearer-токену; 401 — токен невалиден, пользователь удалён/деактивирован."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Невалидный или истёкший токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise credentials_error from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., Coroutine[None, None, User]]:
    """Фабрика зависимостей: пускает только пользователей с одной из ролей."""

    async def check_role(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return check_role


# офис — менеджер и админ: общий гейт управляющих эндпоинтов
office_only = Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN))
