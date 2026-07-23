"""Тесты дашборда: cookie-вход, редиректы навигации и htmx, выход, статика."""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models import UserRole
from app.web.deps import ACCESS_COOKIE
from tests.conftest import UserFactory, web_cookies

PASSWORD = "correct-horse-battery"
LOGIN_URL = "/dashboard/login"


async def login(client: AsyncClient, email: str, password: str, next_url: str = ""):
    data = {"email": email, "password": password}
    if next_url:
        data["next"] = next_url
    return await client.post(LOGIN_URL, data=data)


class TestLoginPage:
    async def test_form_renders(self, client: AsyncClient):
        response = await client.get(LOGIN_URL)

        assert response.status_code == 200
        assert "Вход для офиса" in response.text

    async def test_authenticated_user_skips_form(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        client.cookies.update(web_cookies(user))

        response = await client.get(LOGIN_URL)

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"

    async def test_authenticated_user_follows_next(
        self, client: AsyncClient, make_user: UserFactory
    ):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        client.cookies.update(web_cookies(user))

        response = await client.get(LOGIN_URL, params={"next": "/dashboard/sites/5"})

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/sites/5"

    async def test_authenticated_user_foreign_next_replaced(
        self, client: AsyncClient, make_user: UserFactory
    ):
        """safe_next защищает и GET-ветку: у неё та же поверхность открытого редиректа."""
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        client.cookies.update(web_cookies(user))

        response = await client.get(LOGIN_URL, params={"next": "//evil.example"})

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"


class TestLoginSubmit:
    async def test_manager_logs_in(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD, full_name="Мария Соколова")

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"
        # значение JWT в base64url может содержать любые буквы, поэтому атрибуты
        # ищутся с разделителем «; », а не голой подстрокой по всему заголовку
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith(f"{ACCESS_COOKIE}=")
        assert "; httponly" in cookie
        assert "; samesite=lax" in cookie
        # локальное окружение без TLS — cookie не Secure
        assert "; secure" not in cookie

        dashboard = await client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Мария Соколова" in dashboard.text
        assert "Менеджер" in dashboard.text

    async def test_admin_logs_in(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.ADMIN, password=PASSWORD, full_name="Андрей Волков")

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 303

        dashboard = await client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Андрей Волков" in dashboard.text
        assert "Администратор" in dashboard.text

    async def test_wrong_password_rejected(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await login(client, user.email, "wrong-password")

        assert response.status_code == 401
        assert "Неверный email или пароль" in response.text
        assert "set-cookie" not in response.headers

    async def test_unknown_email_rejected(self, client: AsyncClient):
        response = await login(client, "nobody@example.com", PASSWORD)

        assert response.status_code == 401
        assert "Неверный email или пароль" in response.text

    async def test_inactive_manager_rejected(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        user.is_active = False

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 401

    async def test_foreman_gets_role_message(self, client: AsyncClient, make_user: UserFactory):
        """Пароль подошёл, но роль не офисная — причина отказа называется прямо."""
        user = await make_user(UserRole.FOREMAN, password=PASSWORD)

        response = await login(client, user.email, PASSWORD)

        assert response.status_code == 401
        assert "менеджерам и администраторам" in response.text
        assert "set-cookie" not in response.headers

    async def test_next_preserved(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await login(client, user.email, PASSWORD, next_url="/dashboard/sites/5")

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard/sites/5"

    @pytest.mark.parametrize(
        "bad_next",
        ["//evil.example", "https://evil.example", "/\\evil.example", "javascript:alert(1)"],
    )
    async def test_foreign_next_replaced(
        self, client: AsyncClient, make_user: UserFactory, bad_next: str
    ):
        """Открытый редирект: не-локальный next молча заменяется обзором."""
        user = await make_user(UserRole.MANAGER, password=PASSWORD)

        response = await login(client, user.email, PASSWORD, next_url=bad_next)

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"


class TestWebUserGate:
    async def test_root_redirects_to_dashboard(self, client: AsyncClient):
        response = await client.get("/")

        assert response.status_code == 307
        assert response.headers["location"] == "/dashboard"

    async def test_anonymous_redirected_to_login(self, client: AsyncClient):
        response = await client.get("/dashboard")

        assert response.status_code == 303
        # для страницы по умолчанию ?next= не добавляется
        assert response.headers["location"] == LOGIN_URL

    async def test_deep_link_kept_in_next(self, client: AsyncClient):
        response = await client.get("/dashboard", params={"status": "active"})

        assert response.status_code == 303
        assert response.headers["location"] == f"{LOGIN_URL}?next=%2Fdashboard%3Fstatus%3Dactive"

    async def test_htmx_gets_hx_redirect(self, client: AsyncClient):
        """htmx-запросу нельзя отвечать 303: он вклеил бы форму логина в partial."""
        response = await client.get(
            "/dashboard",
            headers={
                "HX-Request": "true",
                "HX-Current-URL": "http://test/dashboard?status=active",
            },
        )

        assert response.status_code == 401
        assert response.headers["hx-redirect"] == f"{LOGIN_URL}?next=%2Fdashboard%3Fstatus%3Dactive"
        assert "location" not in response.headers

    async def test_htmx_without_current_url(self, client: AsyncClient):
        response = await client.get("/dashboard", headers={"HX-Request": "true"})

        assert response.status_code == 401
        assert response.headers["hx-redirect"] == LOGIN_URL

    async def test_expired_token_redirects(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, expires_minutes=-1))

        response = await client.get("/dashboard")

        assert response.status_code == 303

    async def test_garbage_cookie_redirects(self, client: AsyncClient):
        client.cookies.set(ACCESS_COOKIE, "not-a-jwt")

        response = await client.get("/dashboard")

        assert response.status_code == 303

    async def test_foreman_cookie_rejected(self, client: AsyncClient, make_user: UserFactory):
        """Прораб мог получить токен через API — но дашборд ему всё равно закрыт."""
        user = await make_user(UserRole.FOREMAN, password=PASSWORD)
        client.cookies.update(web_cookies(user))

        response = await client.get("/dashboard")

        assert response.status_code == 303

    async def test_deactivated_user_cookie_rejected(
        self, client: AsyncClient, make_user: UserFactory
    ):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        user.is_active = False
        client.cookies.update(web_cookies(user))

        response = await client.get("/dashboard")

        assert response.status_code == 303

    async def test_unknown_user_cookie_rejected(self, client: AsyncClient):
        client.cookies.set(ACCESS_COOKIE, create_access_token(10**9))

        response = await client.get("/dashboard")

        assert response.status_code == 303


class TestLogout:
    async def test_logout_clears_cookie(self, client: AsyncClient, make_user: UserFactory):
        user = await make_user(UserRole.MANAGER, password=PASSWORD)
        await login(client, user.email, PASSWORD)

        response = await client.post("/dashboard/logout")

        assert response.status_code == 303
        assert response.headers["location"] == LOGIN_URL
        # cookie стёрта — дашборд снова требует вход
        after = await client.get("/dashboard")
        assert after.status_code == 303


class TestStatic:
    async def test_vendor_cached_forever(self, client: AsyncClient):
        response = await client.get("/static/vendor/htmx-2.0.10/htmx.min.js")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"

    async def test_missing_file_404(self, client: AsyncClient):
        response = await client.get("/static/vendor/nope.js")

        assert response.status_code == 404
