"""Схемы пользователей: создание, частичное обновление, ответ API."""

from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.security import MIN_PASSWORD_LENGTH
from app.models import UserRole


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
    telegram_id: int | None = None

    @model_validator(mode="after")
    def password_requires_email(self) -> Self:
        # пароль — это вход в API по email; без email он бесполезен
        if self.password is not None and self.email is None:
            raise ValueError("пароль задаётся вместе с email")
        return self


class UserUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля, null очищает значение."""

    full_name: str | None = Field(default=None, min_length=1)
    role: UserRole | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)
    telegram_id: int | None = None
    is_active: bool | None = None
