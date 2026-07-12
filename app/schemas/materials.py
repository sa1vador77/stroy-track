"""Схемы материалов: создание, частичное обновление, ответ API."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import no_null_updates


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unit: str


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class MaterialUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля."""

    name: str | None = Field(default=None, min_length=1)
    unit: str | None = Field(default=None, min_length=1)

    forbid_null = no_null_updates()
