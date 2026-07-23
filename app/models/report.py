"""Ежедневные отчёты прорабов: работы, численность, фото, расход материалов."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MATERIAL_QUANTITY, Base
from app.models.material import Material


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        # один отчёт прораба по объекту за день; имя явное:
        # конвенция именует составные констрейнты по первой колонке
        UniqueConstraint(
            "site_id", "foreman_id", "report_date", name="uq_daily_reports_site_foreman_date"
        ),
        CheckConstraint("workers_count >= 0", name="workers_count_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("construction_sites.id", ondelete="CASCADE"))
    # RESTRICT: у прораба с отчётами история сохраняется — вместо удаления есть is_active
    foreman_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    # дашборд ежеминутно срезает «сегодня» по всем объектам; составной unique
    # ведёт по site_id и для поиска только по дате бесполезен
    report_date: Mapped[date] = mapped_column(index=True)
    work_description: Mapped[str]
    workers_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # фото и расход материалов удаляет ON DELETE CASCADE в БД,
    # ORM не подгружает их при удалении отчёта
    photos: Mapped[list["ReportPhoto"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )
    material_usages: Mapped[list["ReportMaterialUsage"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )


class ReportPhoto(Base):
    __tablename__ = "report_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str]

    report: Mapped[DailyReport] = relationship(back_populates="photos")


class ReportMaterialUsage(Base):
    __tablename__ = "report_material_usages"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "material_id", name="uq_report_material_usages_report_material"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id", ondelete="CASCADE"))
    material_id: Mapped[int] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(MATERIAL_QUANTITY)

    report: Mapped[DailyReport] = relationship(back_populates="material_usages")
    material: Mapped[Material] = relationship()
