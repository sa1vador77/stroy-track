"""Схемы стройплощадок: создание, частичное обновление, ответ API, назначение прораба."""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import SiteStatus
from app.models.base import PG_INT_MAX
from app.schemas.base import no_null_updates


class ForemanOut(BaseModel):
    """Прораб в составе объекта: без email и telegram_id —
    состав видят и другие прорабы, контакты коллег им не нужны."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    start_date: date
    planned_end_date: date
    status: SiteStatus
    foremen: list[ForemanOut]


class SiteCreate(BaseModel):
    name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    start_date: date
    planned_end_date: date
    status: SiteStatus = SiteStatus.ACTIVE

    @model_validator(mode="after")
    def end_not_before_start(self) -> Self:
        if self.planned_end_date < self.start_date:
            raise ValueError("плановое окончание раньше начала работ")
        return self


class SiteUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля."""

    name: str | None = Field(default=None, min_length=1)
    address: str | None = Field(default=None, min_length=1)
    start_date: date | None = None
    planned_end_date: date | None = None
    status: SiteStatus | None = None

    forbid_null = no_null_updates()


class ForemanAssignment(BaseModel):
    user_id: int = Field(ge=1, le=PG_INT_MAX)
