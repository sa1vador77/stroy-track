"""Схемы бригад: создание, частичное обновление, ответ API."""

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import PG_INT_MAX
from app.schemas.base import no_null_updates


class CrewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    name: str
    size: int


class CrewCreate(BaseModel):
    name: str = Field(min_length=1)
    size: int = Field(ge=1, le=PG_INT_MAX)


class CrewUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля."""

    name: str | None = Field(default=None, min_length=1)
    size: int | None = Field(default=None, ge=1, le=PG_INT_MAX)

    forbid_null = no_null_updates()
