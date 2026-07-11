"""Тесты аутентификации: /auth/login, /auth/me, require_roles."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends
from httpx import AsyncClient

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.security import ALGORITHM, create_access_token
from app.main import app
from app.models import User, UserRole
from tests.conftest import UserFactory

PASSWORD = "correct-horse-battery"

# маршрут для проверки require_roles через полный DI-стек:
# токен -> get_current_user -> проверка роли
_protected = APIRouter()


@_protected.get("/_test/admin-only")
async def _admin_only(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> dict[str, int]:
    return {"user_id": user.id}


app.include_router(_protected)


async def login(client: AsyncClient, email: str, password: str):
    return await client.post("/auth/login", data={"username": email, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestLogin:
    async def test_success_returns_token(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    async def test_wrong_password_401(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await login(client, user.email, "wrong-password")

        assert response.status_code == 401

    async def test_unknown_email_401(self, client: AsyncClient):
        response = await login(client, "nobody@example.com", PASSWORD)

        assert response.status_code == 401

    async def test_user_without_password_401(self, client: AsyncClient, make_user: UserFactory):
        """Прораб, заведённый только для бота (без пароля), не может войти в API."""
        user = await make_user(UserRole.FOREMAN, telegram_id=123456789)

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 401

    async def test_inactive_user_401(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        user.is_active = False

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 401


class TestCurrentUser:
    async def test_me_returns_user(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.ADMIN, password=PASSWORD, full_name="Админ Админыч")
        token = (await login(client, user.email, PASSWORD)).json()["access_token"]

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == user.id
        assert body["full_name"] == "Админ Админыч"
        assert body["role"] == "admin"

    async def test_no_token_401(self, client: AsyncClient):
        response = await client.get("/auth/me")

        assert response.status_code == 401

    async def test_garbage_token_401(self, client: AsyncClient):
        response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

        assert response.status_code == 401

    async def test_expired_token_401(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        token = create_access_token(user.id, expires_minutes=-1)

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 401

    async def test_token_of_deactivated_user_401(self, client: AsyncClient, make_user: UserFactory):
        """Токен выдан, пока пользователь был активен, — после деактивации не работает."""
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        token = (await login(client, user.email, PASSWORD)).json()["access_token"]
        user.is_active = False

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 401

    async def test_token_of_unknown_user_401(self, client: AsyncClient):
        """Валидный токен пользователя, которого уже нет в БД."""
        token = create_access_token(10**9)

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 401

    async def test_token_with_non_numeric_sub_401(self, client: AsyncClient):
        token = _forge_token({"sub": "abc"})

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 401

    async def test_token_without_sub_401(self, client: AsyncClient):
        token = _forge_token({})

        response = await client.get("/auth/me", headers=bearer(token))

        assert response.status_code == 401


def _forge_token(claims: dict) -> str:
    """Корректно подписанный токен с произвольными клеймами — проверка разбора sub."""
    payload = {"exp": datetime.now(UTC) + timedelta(minutes=5), **claims}
    return jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM)


class TestRequireRoles:
    async def test_allowed_role_200(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.ADMIN, password=PASSWORD)
        token = (await login(client, user.email, PASSWORD)).json()["access_token"]

        response = await client.get("/_test/admin-only", headers=bearer(token))

        assert response.status_code == 200
        assert response.json() == {"user_id": user.id}

    async def test_other_role_403(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.FOREMAN, password=PASSWORD)
        token = (await login(client, user.email, PASSWORD)).json()["access_token"]

        response = await client.get("/_test/admin-only", headers=bearer(token))

        assert response.status_code == 403

    async def test_no_token_401(self, client: AsyncClient):
        response = await client.get("/_test/admin-only")

        assert response.status_code == 401
