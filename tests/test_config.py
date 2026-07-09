import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_prod_refuses_default_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(environment="prod", secret_key="dev-secret-change-me", _env_file=None)


def test_prod_starts_with_custom_secret_key():
    settings = Settings(environment="prod", secret_key="a" * 64, _env_file=None)

    assert settings.secret_key == "a" * 64
