"""Справочник материалов и их поставки на объекты."""

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MATERIAL_QUANTITY, Base


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    unit: Mapped[str]  # единица измерения: т, м3, шт …


class MaterialDelivery(Base):
    __tablename__ = "material_deliveries"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("construction_sites.id", ondelete="CASCADE"), index=True
    )
    # RESTRICT: материал со связанными поставками удалить нельзя — история важнее справочника
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(MATERIAL_QUANTITY)
    # KPI дашборда считает «поставки за сегодня» срезом только по дате
    delivery_date: Mapped[date] = mapped_column(index=True)
    supplier: Mapped[str]

    material: Mapped[Material] = relationship()
