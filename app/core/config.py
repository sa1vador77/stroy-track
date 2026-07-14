"""Настройки приложения: переменные окружения, .env, DSN базы."""

from functools import lru_cache
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET_KEY = "dev-secret-change-me"
_DEV_POSTGRES_PASSWORD = "stroytrack"


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения и .env."""

    # .env.bot лежит отдельно: токен бота не попадает в окружение API-контейнера
    model_config = SettingsConfigDict(env_file=(".env", ".env.bot"), extra="ignore")

    environment: Literal["local", "prod"] = "local"
    log_json: bool = False

    # Дефолт только для локальной разработки; prod с ним не стартует (см. валидатор)
    secret_key: str = _DEV_SECRET_KEY
    access_token_expire_minutes: int = 60

    # нужен только процессу бота, поэтому не обязателен: API и тесты живут без него,
    # а бот сам падает на старте, если токена нет (app/bot/__main__.py)
    bot_token: str | None = None

    # в этом поясе считается «сегодня» для отчётов: вечерний отчёт по UTC-дате
    # уехал бы на другой день
    company_tz: str = "Europe/Moscow"

    @field_validator("company_tz")
    @classmethod
    def tz_must_exist(cls, value: str) -> str:
        # неизвестный пояс валит процесс на старте, а не первый /report;
        # ZoneInfoNotFoundError — наследник KeyError, pydantic оборачивает только ValueError
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Неизвестный часовой пояс: {value}") from None
        return value

    @property
    def company_tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.company_tz)

    @model_validator(mode="after")
    def forbid_weak_secrets_outside_local(self) -> Self:
        if self.environment == "local":
            return self
        if self.secret_key == _DEV_SECRET_KEY:
            raise ValueError(
                "В prod нужен собственный SECRET_KEY (сгенерировать: openssl rand -hex 32)"
            )
        # HS256 требует ключ не короче 256 бит: короткий восстанавливается
        # офлайн-перебором по одному перехваченному токену
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY короче 32 символов (сгенерировать: openssl rand -hex 32)")
        if self.postgres_password == _DEV_POSTGRES_PASSWORD:
            raise ValueError("В prod нужен собственный POSTGRES_PASSWORD")
        return self

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "stroytrack"
    postgres_password: str = _DEV_POSTGRES_PASSWORD
    postgres_db: str = "stroytrack"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
