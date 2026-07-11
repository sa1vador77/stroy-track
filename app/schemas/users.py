"""Схемы пользователей: создание, частичное обновление, ответ API."""

from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.security import MIN_PASSWORD_LENGTH
from app.models import UserRole
from app.models.base import PG_BIGINT_MAX


def _lowercase_email(value: str | None) -> str | None:
    # email хранится в нижнем регистре: уникальность и логин не зависят от регистра ввода
    return value.lower() if value else value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str | None
    role: UserRole
    telegram_id: int | None
    is_active: bool


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1)
    role: UserRole
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)
    telegram_id: int | None = Field(default=None, ge=1, le=PG_BIGINT_MAX)

    normalize_email = field_validator("email")(_lowercase_email)

    @model_validator(mode="after")
    def password_requires_email(self) -> Self:
        # пароль — это вход в API по email; без email он бесполезен
        if self.password is not None and self.email is None:
            raise ValueError("пароль задаётся вместе с email")
        return self


# nullable-колонки: null в PATCH означает «очистить значение»
_CLEARABLE = {"email", "password", "telegram_id"}


class UserUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля, null очищает значение."""

    full_name: str | None = Field(default=None, min_length=1)
    role: UserRole | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)
    telegram_id: int | None = Field(default=None, ge=1, le=PG_BIGINT_MAX)
    is_active: bool | None = None

    normalize_email = field_validator("email")(_lowercase_email)

    @model_validator(mode="after")
    def forbid_null_for_required(self) -> Self:
        # для NOT NULL колонок явный null — ошибка клиента, а не «очистка»
        for name in self.model_fields_set - _CLEARABLE:
            if getattr(self, name) is None:
                raise ValueError(f"поле {name} не может быть null")
        return self
