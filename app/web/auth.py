"""Вход и выход дашборда: JWT в HttpOnly-cookie, скользящее продление сессии."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import RedirectResponse, Response

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.security import authenticate_user, create_access_token, decode_access_token
from app.web.deps import ACCESS_COOKIE, LOGIN_URL, OFFICE_ROLES, find_web_user, safe_next
from app.web.templating import templates

router = APIRouter(prefix="/dashboard", include_in_schema=False)

LOGOUT_URL = "/dashboard/logout"


def _set_session_cookie(response: Response, user_id: int) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(user_id),
        # cookie живёт столько же, сколько сам токен
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "prod",
    )


@router.get("/login")
async def login_form(
    request: Request,
    session: SessionDep,
    next_url: Annotated[str | None, Query(alias="next")] = None,
) -> Response:
    if await find_web_user(request, session) is not None:
        # уже вошёл — форма ни к чему
        return RedirectResponse(safe_next(next_url), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"next_url": next_url or ""})


@router.post("/login")
async def login_submit(
    request: Request,
    session: SessionDep,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_url: Annotated[str, Form(alias="next")] = "",
) -> Response:
    user = await authenticate_user(session, email, password)
    if user is None:
        # один ответ на неверный пароль и неизвестный email — как в JSON-API
        error = "Неверный email или пароль"
    elif user.role not in OFFICE_ROLES:
        # пароль подошёл — причину отказа можно назвать прямо
        error = "Дашборд доступен менеджерам и администраторам"
    else:
        response = RedirectResponse(safe_next(next_url), status_code=status.HTTP_303_SEE_OTHER)
        _set_session_cookie(response, user.id)
        return response
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "email": email, "next_url": next_url},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(LOGIN_URL, status_code=status.HTTP_303_SEE_OTHER)
    # стирается только cookie; сам JWT валиден до exp —
    # осознанная цена stateless-токена при TTL в час
    response.delete_cookie(ACCESS_COOKIE)
    return response


async def sliding_session(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Скользящая сессия: живой запрос к дашборду перевыпускает cookie на полный TTL.

    Активный пользователь не разлогинивается вовсе, покинутый — через час:
    poll обзора сессию не продлевает, иначе забытая вкладка держала бы её вечно.
    Это middleware, а не зависимость: FastAPI игнорирует Set-Cookie на
    инжектированном Response, когда эндпоинт сам возвращает TemplateResponse.
    Абсолютного потолка у окна нет — принято осознанно, уровень риска как у
    обычных серверных сессий с продлением."""
    response = await call_next(request)
    if not request.url.path.startswith("/dashboard"):
        return response
    # login сам ставит свежую cookie, а после logout продление воскресило бы
    # только что стёртую
    if request.url.path in (LOGIN_URL, LOGOUT_URL):
        return response
    if request.headers.get("HX-Trigger") == "overview":
        return response
    token = request.cookies.get(ACCESS_COOKIE)
    if token is None:
        return response
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        # просроченный или битый токен не продлевается — это и есть разлогин
        return response
    _set_session_cookie(response, user_id)
    return response
