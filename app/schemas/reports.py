"""Схемы чтения отчётов: отчёт отдаётся целиком — с фото и расходом материалов."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReportPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str


class ReportMaterialUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_id: int
    quantity: Decimal


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    foreman_id: int
    report_date: date
    work_description: str
    workers_count: int
    created_at: datetime
    photos: list[ReportPhotoOut]
    material_usages: list[ReportMaterialUsageOut]
