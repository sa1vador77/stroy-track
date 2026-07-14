"""Общие фикстуры: тестовая БД, транзакция на тест, HTTP-клиент, фабрика пользователей."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import (
    Base,
    ConstructionSite,
    Crew,
    Material,
    MaterialDelivery,
    SiteStatus,
    User,
    UserRole,
)


def _replace_db(url: str, db_name: str) -> str:
    return url.rsplit("/", 1)[0] + f"/{db_name}"


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Отдельная БД stroytrack_test: создаётся при первом запуске, схема — свежая на сессию."""
    settings = get_settings()
    test_db = f"{settings.postgres_db}_test"

    admin_engine = create_async_engine(
        _replace_db(settings.database_url, "postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": test_db}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    await admin_engine.dispose()

    engine = create_async_engine(_replace_db(settings.database_url, test_db))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Каждый тест — внутри внешней транзакции, которая откатывается в конце:
    commit() в коде приложения работает через SAVEPOINT, база остаётся чистой."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(user: User) -> dict[str, str]:
    """Authorization-заголовок от имени пользователя — токен куётся напрямую, минуя /auth/login."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


type UserFactory = Callable[..., Awaitable[User]]


@pytest.fixture
def make_user(db_session: AsyncSession) -> UserFactory:
    counter = 0

    async def _make(
        role: UserRole = UserRole.FOREMAN,
        *,
        email: str | None = None,
        password: str | None = None,
        telegram_id: int | None = None,
        full_name: str = "Тест Тестович",
    ) -> User:
        nonlocal counter
        counter += 1
        user = User(
            full_name=full_name,
            role=role,
            email=email or f"user{counter}@example.com",
            password_hash=hash_password(password) if password else None,
            telegram_id=telegram_id,
        )
        db_session.add(user)
        await db_session.commit()
        return user

    return _make


type SiteFactory = Callable[..., Awaitable[ConstructionSite]]


@pytest.fixture
def make_site(db_session: AsyncSession) -> SiteFactory:
    counter = 0

    async def _make(
        *,
        name: str | None = None,
        status: SiteStatus = SiteStatus.ACTIVE,
        foremen: list[User] | None = None,
    ) -> ConstructionSite:
        nonlocal counter
        counter += 1
        site = ConstructionSite(
            name=name or f"ЖК Тестовый-{counter}",
            address="г. Тестоград, ул. Строителей, 1",
            start_date=date(2026, 1, 12),
            planned_end_date=date(2027, 6, 30),
            status=status,
            foremen=foremen or [],
        )
        db_session.add(site)
        await db_session.commit()
        return site

    return _make


type MaterialFactory = Callable[..., Awaitable[Material]]


@pytest.fixture
def make_material(db_session: AsyncSession) -> MaterialFactory:
    counter = 0

    async def _make(*, name: str | None = None, unit: str = "т") -> Material:
        nonlocal counter
        counter += 1
        material = Material(name=name or f"Материал №{counter}", unit=unit)
        db_session.add(material)
        await db_session.commit()
        return material

    return _make


type DeliveryFactory = Callable[..., Awaitable[MaterialDelivery]]


@pytest.fixture
def make_delivery(db_session: AsyncSession) -> DeliveryFactory:
    async def _make(
        site: ConstructionSite,
        material: Material,
        *,
        quantity: Decimal = Decimal("10"),
        delivery_date: date = date(2026, 7, 1),
        supplier: str = "СтройБаза №1",
    ) -> MaterialDelivery:
        delivery = MaterialDelivery(
            site_id=site.id,
            material_id=material.id,
            quantity=quantity,
            delivery_date=delivery_date,
            supplier=supplier,
        )
        db_session.add(delivery)
        await db_session.commit()
        return delivery

    return _make


type CrewFactory = Callable[..., Awaitable[Crew]]


@pytest.fixture
def make_crew(db_session: AsyncSession) -> CrewFactory:
    counter = 0

    async def _make(site: ConstructionSite, *, name: str | None = None, size: int = 8) -> Crew:
        nonlocal counter
        counter += 1
        crew = Crew(site_id=site.id, name=name or f"Бригада №{counter}", size=size)
        db_session.add(crew)
        await db_session.commit()
        return crew

    return _make
