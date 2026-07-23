"""Зависимости страниц: пользователь из cookie, редиректы вместо JSON-ошибок."""

from typing import Annotated
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.core.security import decode_access_token
from app.models import User, UserRole

ACCESS_COOKIE = "access_token"
LOGIN_URL = "/dashboard/login"
OFFICE_ROLES = (UserRole.MANAGER, UserRole.ADMIN)


def safe_next(next_url: str | None) -> str:
    """Цель редиректа после входа: только локальный путь, иначе — обзор.

    «//host» и «/\\host» браузеры трактуют как схемо-относительные URL —
    получился бы открытый редирект; управляющие символы — инъекция в Location."""
    if (
        next_url
        and next_url.startswith("/")
        and not next_url.startswith("//")
        and "\\" not in next_url
        and not any(char < " " for char in next_url)
    ):
        return next_url
    return "/dashboard"


def _login_redirect(request: Request) -> HTTPException:
    """Невалидная сессия: браузеру — 303 на форму входа, htmx-запросу — HX-Redirect.

    Обычный 303 htmx выполнил бы сам и вклеил форму логина внутрь
    partial-контейнера; HX-Redirect делает полностраничный переход."""
    if request.headers.get("HX-Request"):
        # у partial-запроса свой URL — адрес страницы htmx присылает отдельно
        current = urlsplit(request.headers.get("HX-Current-URL", ""))
        page, query = current.path, current.query
    else:
        page, query = request.url.path, request.url.query
    if query:
        page += f"?{query}"
    target = LOGIN_URL
    # /dashboard — цель по умолчанию, для неё ?next= только шумит в адресе
    if safe_next(page) != "/dashboard":
        target += "?" + urlencode({"next": page})
    if request.headers.get("HX-Request"):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": target})
    return HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": target})


async def find_web_user(request: Request, session: AsyncSession) -> User | None:
    """Владелец валидной cookie с офисной ролью, иначе None."""
    token = request.cookies.get(ACCESS_COOKIE)
    if token is None:
        return None
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        return None
    user = await session.get(User, user_id)
    # прораб с API-токеном в cookie отсекается здесь же: дашборд только для офиса
    if user is None or not user.is_active or user.role not in OFFICE_ROLES:
        return None
    return user


async def get_web_user(request: Request, session: SessionDep) -> User:
    user = await find_web_user(request, session)
    if user is None:
        raise _login_redirect(request)
    return user


WebUser = Annotated[User, Depends(get_web_user)]
