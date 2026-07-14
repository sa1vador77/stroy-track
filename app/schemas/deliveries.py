"""Схемы поставок материалов: создание, частичное обновление, ответ API."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.base import PG_INT_MAX
from app.schemas.base import no_null_updates


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    material_id: int
    quantity: Decimal
    delivery_date: date
    supplier: str

    @field_serializer("quantity")
    def _canonical_quantity(self, value: Decimal) -> Decimal:
        # NUMERIC(12, 3) добивает значение до трёх знаков при чтении из БД,
        # у свежесозданного объекта масштаб — как прислал клиент; канонизируем,
        # чтобы представление не зависело от того, POST это или GET
        return value.quantize(Decimal("0.001"))


class DeliveryCreate(BaseModel):
    material_id: int = Field(ge=1, le=PG_INT_MAX)
    # границы повторяют Numeric(12, 3) и CHECK quantity > 0 в БД:
    # клиент получает 422 на валидации, а не ошибку из базы
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    delivery_date: date
    supplier: str = Field(min_length=1)


class DeliveryUpdate(BaseModel):
    """Частичное обновление: применяются только присланные поля."""

    material_id: int | None = Field(default=None, ge=1, le=PG_INT_MAX)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    delivery_date: date | None = None
    supplier: str | None = Field(default=None, min_length=1)

    forbid_null = no_null_updates()
