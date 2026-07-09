from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения. Читаются из переменных окружения и .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_json: bool = False

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "stroytrack"
    postgres_password: str = "stroytrack"
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
