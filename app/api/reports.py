"""Чтение отчётов прорабов: отчёты создаёт телеграм-бот, API отдаёт их офису и прорабам."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select, select

from app.api.deps import CurrentUser, PathID, SessionDep
from app.api.sites import ensure_site_access, get_site_or_404
from app.models import DailyReport
from app.schemas.reports import ReportOut

router = APIRouter(tags=["reports"])


def _report_query() -> Select[tuple[DailyReport]]:
    # фото и расход материалов входят в каждый ответ; selectinload — отдельными
    # запросами, ленивые дозагрузки в asyncio запрещены
    return select(DailyReport).options(
        selectinload(DailyReport.photos), selectinload(DailyReport.material_usages)
    )


@router.get("/sites/{site_id}/reports")
async def list_reports(site_id: PathID, session: SessionDep, user: CurrentUser) -> list[ReportOut]:
    """Отчёты объекта в хронологическом порядке; прорабу доступны только его объекты."""
    site = await get_site_or_404(session, site_id)
    ensure_site_access(site, user)
    reports = await session.scalars(
        _report_query()
        .where(DailyReport.site_id == site.id)
        .order_by(DailyReport.report_date, DailyReport.id)
    )
    return [ReportOut.model_validate(report) for report in reports]


@router.get("/reports/{report_id}")
async def get_report(report_id: PathID, session: SessionDep, user: CurrentUser) -> ReportOut:
    """Отчёт по id; прорабу доступны только отчёты его объектов."""
    report = await session.scalar(_report_query().where(DailyReport.id == report_id))
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Отчёт не найден")
    # объект гарантирован FK; get_site_or_404 нужен ради прорабов для проверки доступа
    site = await get_site_or_404(session, report.site_id)
    ensure_site_access(site, user)
    return ReportOut.model_validate(report)
