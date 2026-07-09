from collections.abc import AsyncIterator, Awaitable, Callable

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
from app.core.security import hash_password
from app.main import app
from app.models import Base, User, UserRole


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
