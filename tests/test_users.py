"""Тесты CRUD пользователей и CLI-команды create-admin."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import create_admin
from app.models import User, UserRole
from tests.conftest import UserFactory, auth_headers

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def admin(make_user: UserFactory) -> User:
    return await make_user(UserRole.ADMIN)


class TestAccess:
    async def test_no_token_401(self, client: AsyncClient):
        response = await client.get("/users")

        assert response.status_code == 401

    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.FOREMAN])
    async def test_non_admin_403(self, client: AsyncClient, make_user: UserFactory, role: UserRole):
        user = await make_user(role)

        response = await client.get("/users", headers=auth_headers(user))

        assert response.status_code == 403


class TestCreateUser:
    async def test_manager_with_password_can_login(self, client: AsyncClient, admin: User):
        response = await client.post(
            "/users",
            json={
                "full_name": "Мария Менеджер",
                "role": "manager",
                "email": "maria@example.com",
                "password": PASSWORD,
            },
            headers=auth_headers(admin),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["role"] == "manager"
        assert "password" not in body
        assert "password_hash" not in body

        login = await client.post(
            "/auth/login", data={"username": "maria@example.com", "password": PASSWORD}
        )
        assert login.status_code == 200

    async def test_foreman_with_telegram_only(self, client: AsyncClient, admin: User):
        """Прораба заводят без email и пароля — он входит только через бота."""
        response = await client.post(
            "/users",
            json={"full_name": "Пётр Прораб", "role": "foreman", "telegram_id": 123456789},
            headers=auth_headers(admin),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] is None
        assert body["telegram_id"] == 123456789

    async def test_password_without_email_422(self, client: AsyncClient, admin: User):
        response = await client.post(
            "/users",
            json={"full_name": "Пётр Прораб", "role": "foreman", "password": PASSWORD},
            headers=auth_headers(admin),
        )

        assert response.status_code == 422

    async def test_short_password_422(self, client: AsyncClient, admin: User):
        response = await client.post(
            "/users",
            json={
                "full_name": "Мария Менеджер",
                "role": "manager",
                "email": "maria@example.com",
                "password": "short",
            },
            headers=auth_headers(admin),
        )

        assert response.status_code == 422

    async def test_duplicate_email_409(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        existing = await make_user(UserRole.MANAGER)

        response = await client.post(
            "/users",
            json={"full_name": "Дубль", "role": "manager", "email": existing.email},
            headers=auth_headers(admin),
        )

        assert response.status_code == 409
        assert "email" in response.json()["detail"]

    async def test_duplicate_telegram_id_409(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        await make_user(UserRole.FOREMAN, telegram_id=555)

        response = await client.post(
            "/users",
            json={"full_name": "Дубль", "role": "foreman", "telegram_id": 555},
            headers=auth_headers(admin),
        )

        assert response.status_code == 409
        assert "telegram_id" in response.json()["detail"]


class TestReadUsers:
    async def test_list_ordered_by_id(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        await make_user(UserRole.FOREMAN)
        await make_user(UserRole.MANAGER)

        response = await client.get("/users", headers=auth_headers(admin))

        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert len(ids) == 3
        assert ids == sorted(ids)

    async def test_get_by_id(self, client: AsyncClient, admin: User, make_user: UserFactory):
        user = await make_user(UserRole.FOREMAN, full_name="Пётр Прораб")

        response = await client.get(f"/users/{user.id}", headers=auth_headers(admin))

        assert response.status_code == 200
        assert response.json()["full_name"] == "Пётр Прораб"

    async def test_unknown_id_404(self, client: AsyncClient, admin: User):
        response = await client.get("/users/1000000", headers=auth_headers(admin))

        assert response.status_code == 404


class TestUpdateUser:
    async def test_partial_update_keeps_other_fields(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        user = await make_user(UserRole.FOREMAN, telegram_id=777)

        response = await client.patch(
            f"/users/{user.id}",
            json={"full_name": "Новое Имя"},
            headers=auth_headers(admin),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["full_name"] == "Новое Имя"
        assert body["role"] == "foreman"
        assert body["telegram_id"] == 777

    async def test_promote_foreman_to_manager(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        user = await make_user(UserRole.FOREMAN)

        response = await client.patch(
            f"/users/{user.id}", json={"role": "manager"}, headers=auth_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["role"] == "manager"

    async def test_change_password(self, client: AsyncClient, admin: User, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await client.patch(
            f"/users/{user.id}",
            json={"password": "new-secret-password"},
            headers=auth_headers(admin),
        )

        assert response.status_code == 200
        old = await client.post("/auth/login", data={"username": user.email, "password": PASSWORD})
        new = await client.post(
            "/auth/login", data={"username": user.email, "password": "new-secret-password"}
        )
        assert old.status_code == 401
        assert new.status_code == 200

    async def test_deactivated_user_token_rejected(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        user = await make_user(UserRole.MANAGER)

        response = await client.patch(
            f"/users/{user.id}", json={"is_active": False}, headers=auth_headers(admin)
        )

        assert response.status_code == 200
        me = await client.get("/auth/me", headers=auth_headers(user))
        assert me.status_code == 401

    async def test_clear_telegram_id_with_null(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        user = await make_user(UserRole.FOREMAN, telegram_id=777)

        response = await client.patch(
            f"/users/{user.id}", json={"telegram_id": None}, headers=auth_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["telegram_id"] is None

    async def test_password_for_user_without_email_400(
        self, client: AsyncClient, admin: User, make_user: UserFactory, db_session: AsyncSession
    ):
        user = await make_user(UserRole.FOREMAN, telegram_id=777)
        user.email = None
        await db_session.commit()

        response = await client.patch(
            f"/users/{user.id}", json={"password": PASSWORD}, headers=auth_headers(admin)
        )

        assert response.status_code == 400

    async def test_cannot_deactivate_self(self, client: AsyncClient, admin: User):
        response = await client.patch(
            f"/users/{admin.id}", json={"is_active": False}, headers=auth_headers(admin)
        )

        assert response.status_code == 409

    async def test_cannot_demote_self(self, client: AsyncClient, admin: User):
        response = await client.patch(
            f"/users/{admin.id}", json={"role": "manager"}, headers=auth_headers(admin)
        )

        assert response.status_code == 409

    async def test_admin_can_rename_self(self, client: AsyncClient, admin: User):
        response = await client.patch(
            f"/users/{admin.id}", json={"full_name": "Новый Админ"}, headers=auth_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["full_name"] == "Новый Админ"

    async def test_unknown_id_404(self, client: AsyncClient, admin: User):
        response = await client.patch(
            "/users/1000000", json={"full_name": "Никто"}, headers=auth_headers(admin)
        )

        assert response.status_code == 404

    async def test_duplicate_email_409(
        self, client: AsyncClient, admin: User, make_user: UserFactory
    ):
        first = await make_user(UserRole.MANAGER)
        second = await make_user(UserRole.MANAGER)

        response = await client.patch(
            f"/users/{second.id}", json={"email": first.email}, headers=auth_headers(admin)
        )

        assert response.status_code == 409


class TestCreateAdminCli:
    async def test_creates_admin(self, db_session: AsyncSession):
        admin = await create_admin(
            db_session, email="root@example.com", password=PASSWORD, full_name="Главный"
        )

        assert admin.id is not None
        assert admin.role == UserRole.ADMIN
        assert admin.password_hash != PASSWORD

    async def test_existing_email_rejected(self, db_session: AsyncSession, make_user: UserFactory):
        existing = await make_user(UserRole.MANAGER)

        with pytest.raises(ValueError, match="уже существует"):
            await create_admin(
                db_session, email=existing.email, password=PASSWORD, full_name="Главный"
            )

    async def test_short_password_rejected(self, db_session: AsyncSession):
        with pytest.raises(ValueError, match="короче"):
            await create_admin(
                db_session, email="root@example.com", password="short", full_name="Главный"
            )
