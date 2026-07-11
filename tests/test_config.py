"""Тесты валидации настроек."""

import pytest
from pydantic import ValidationError

from app.core.config import _DEV_SECRET_KEY, Settings

STRONG_KEY = "a" * 64


def test_prod_refuses_default_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(environment="prod", secret_key=_DEV_SECRET_KEY, _env_file=None)


def test_prod_refuses_short_secret_key():
    with pytest.raises(ValidationError, match="короче 32"):
        Settings(
            environment="prod",
            secret_key="prod123",
            postgres_password="prod-db-password",
            _env_file=None,
        )


def test_prod_refuses_default_postgres_password():
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(environment="prod", secret_key=STRONG_KEY, _env_file=None)


def test_prod_starts_with_strong_settings():
    settings = Settings(
        environment="prod",
        secret_key=STRONG_KEY,
        postgres_password="prod-db-password",
        _env_file=None,
    )

    assert settings.secret_key == STRONG_KEY


def test_local_allows_dev_defaults():
    settings = Settings(environment="local", _env_file=None)

    assert settings.secret_key == _DEV_SECRET_KEY
