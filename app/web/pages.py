"""Страницы дашборда."""

from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.core.clock import company_today
from app.models import (
    ConstructionSite,
    DailyReport,
    MaterialDelivery,
    SiteStatus,
    User,
    UserRole,
    site_assignments,
)
from app.web.deps import WebUser
from app.web.templating import templates

router = APIRouter(include_in_schema=False)

# сегменты фильтра обзора: значение query-параметра -> подпись кнопки
STATUS_FILTERS = [
    ("active", "Активные"),
    ("suspended", "Приостановленные"),
    ("completed", "Завершённые"),
    ("all", "Все"),
]
_VALID_FILTERS = {value for value, _ in STATUS_FILTERS}

STATUS_LABELS = {
    SiteStatus.ACTIVE: "Активен",
    SiteStatus.SUSPENDED: "Приостановлен",
    SiteStatus.COMPLETED: "Завершён",
}
STATUS_BADGES = {
    SiteStatus.ACTIVE: "bg-success-lt",
    SiteStatus.SUSPENDED: "bg-warning-lt",
    SiteStatus.COMPLETED: "bg-secondary-lt",
}


@dataclass
class ForemanChip:
    full_name: str
    submitted: bool


@dataclass
class SiteCard:
    id: int
    name: str
    address: str
    status: SiteStatus
    foremen: list[ForemanChip]
    workers_today: int

    @property
    def submitted_count(self) -> int:
        return sum(chip.submitted for chip in self.foremen)

    @property
    def needs_attention(self) -> bool:
        """Активный объект, по которому сегодня ждут хотя бы одного отчёта."""
        return self.status is SiteStatus.ACTIVE and self.submitted_count < len(self.foremen)


@dataclass
class Kpi:
    active_sites: int
    submitted: int
    expected: int
    workers: int
    deliveries: int


async def _load_kpi(session: AsyncSession) -> Kpi:
    """Сводка по всей компании: один запрос из пяти скалярных подзапросов."""
    today = company_today()
    # «ожидается» — предикат «кто должен сдать сегодня» из напоминаний
    # (scheduler/reminders.py): активный объект и активный прораб. Прораб без
    # telegram_id остаётся в счётчике, хотя напоминание ему не уйдёт, — эту
    # дыру конфигурации офис и должен увидеть на дашборде
    expected_pairs = (
        select(func.count())
        .select_from(site_assignments)
        .join(User, User.id == site_assignments.c.user_id)
        .join(ConstructionSite, ConstructionSite.id == site_assignments.c.site_id)
        .where(
            User.role == UserRole.FOREMAN,
            User.is_active,
            ConstructionSite.status == SiteStatus.ACTIVE,
        )
    )
    submitted_pairs = expected_pairs.join(
        DailyReport,
        and_(
            DailyReport.site_id == site_assignments.c.site_id,
            DailyReport.foreman_id == site_assignments.c.user_id,
            DailyReport.report_date == today,
        ),
    )
    active_sites = (
        select(func.count())
        .select_from(ConstructionSite)
        .where(ConstructionSite.status == SiteStatus.ACTIVE)
    )
    # рабочие считаются по той же популяции отчётов, что и submitted: иначе
    # «сдал и деактивирован» давал бы на экране «0 отчётов, но 9 рабочих»
    workers = submitted_pairs.with_only_columns(
        func.coalesce(func.sum(DailyReport.workers_count), 0)
    )
    deliveries = (
        select(func.count())
        .select_from(MaterialDelivery)
        .where(MaterialDelivery.delivery_date == today)
    )
    row = (
        await session.execute(
            select(
                active_sites.scalar_subquery(),
                submitted_pairs.scalar_subquery(),
                expected_pairs.scalar_subquery(),
                workers.scalar_subquery(),
                deliveries.scalar_subquery(),
            )
        )
    ).one()
    return Kpi(
        active_sites=row[0], submitted=row[1], expected=row[2], workers=row[3], deliveries=row[4]
    )


def _search_pattern(query: str) -> str:
    # % и _ в пользовательском вводе — литералы, а не метасимволы LIKE
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _load_cards(session: AsyncSession, status: str, query: str) -> list[SiteCard]:
    today = company_today()
    sites_stmt = select(ConstructionSite)
    if status != "all":
        sites_stmt = sites_stmt.where(ConstructionSite.status == SiteStatus(status))
    if query:
        sites_stmt = sites_stmt.where(
            ConstructionSite.name.ilike(_search_pattern(query), escape="\\")
        )
    sites = (await session.scalars(sites_stmt)).all()

    chips: dict[int, list[ForemanChip]] = {}
    workers: dict[int, int] = {}
    site_ids = [site.id for site in sites]
    if site_ids:
        # прорабы с флагом «сдал сегодня»: LEFT JOIN к отчёту пары за сегодня
        chip_rows = await session.execute(
            select(site_assignments.c.site_id, User.full_name, DailyReport.id.is_not(None))
            .join_from(site_assignments, User, User.id == site_assignments.c.user_id)
            .outerjoin(
                DailyReport,
                and_(
                    DailyReport.site_id == site_assignments.c.site_id,
                    DailyReport.foreman_id == site_assignments.c.user_id,
                    DailyReport.report_date == today,
                ),
            )
            .where(
                site_assignments.c.site_id.in_(site_ids),
                User.role == UserRole.FOREMAN,
                User.is_active,
            )
            .order_by(User.full_name, User.id)
        )
        for site_id, full_name, submitted in chip_rows:
            chips.setdefault(site_id, []).append(ForemanChip(full_name, submitted))

        # та же популяция, что у чипов: отчёт учитывается, пока прораб активен
        # и назначен на объект — цифры карточки не противоречат друг другу
        workers_rows = await session.execute(
            select(site_assignments.c.site_id, func.sum(DailyReport.workers_count))
            .join_from(site_assignments, User, User.id == site_assignments.c.user_id)
            .join(
                DailyReport,
                and_(
                    DailyReport.site_id == site_assignments.c.site_id,
                    DailyReport.foreman_id == site_assignments.c.user_id,
                    DailyReport.report_date == today,
                ),
            )
            .where(
                site_assignments.c.site_id.in_(site_ids),
                User.role == UserRole.FOREMAN,
                User.is_active,
            )
            .group_by(site_assignments.c.site_id)
        )
        workers = dict(workers_rows.all())

    cards = [
        SiteCard(
            id=site.id,
            name=site.name,
            address=site.address,
            status=site.status,
            foremen=chips.get(site.id, []),
            workers_today=workers.get(site.id, 0),
        )
        for site in sites
    ]
    # «требуют внимания» сверху, внутри групп — по алфавиту
    cards.sort(key=lambda card: (not card.needs_attention, card.name.lower()))
    return cards


def _normalize(status: str | None, query: str | None) -> tuple[str, str]:
    # мусор в query-параметрах — не повод для 422 на странице
    if status not in _VALID_FILTERS:
        status = "active"
    return status, (query or "").strip()


def _page_url(status: str, query: str) -> str:
    """Канонический адрес обзора; значения по умолчанию не шумят в адресной строке."""
    params = {}
    if status != "active":
        params["status"] = status
    if query:
        params["q"] = query
    return "/dashboard" + (f"?{urlencode(params)}" if params else "")


async def _overview_context(session: AsyncSession, status: str, query: str) -> dict:
    return {
        "kpi": await _load_kpi(session),
        "cards": await _load_cards(session, status, query),
        "status": status,
        "q": query,
        "status_filters": STATUS_FILTERS,
        "status_labels": STATUS_LABELS,
        "status_badges": STATUS_BADGES,
    }


@router.get("/")
async def index() -> RedirectResponse:
    """Корень сайта — это дашборд."""
    return RedirectResponse("/dashboard")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: WebUser,
    session: SessionDep,
    status: str | None = None,
    q: str | None = None,
) -> Response:
    status, q = _normalize(status, q)
    context = await _overview_context(session, status, q)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, **context})


@router.get("/dashboard/overview")
async def dashboard_overview(
    request: Request,
    _: WebUser,
    session: SessionDep,
    status: str | None = None,
    q: str | None = None,
) -> Response:
    """Partial обзора: KPI и карточки — для формы фильтра и 60-секундного poll'а."""
    status, q = _normalize(status, q)
    if not request.headers.get("HX-Request"):
        # фрагмент вне htmx бесполезен — прямой заход уводим на полную страницу
        return RedirectResponse(_page_url(status, q))
    response = templates.TemplateResponse(
        request, "_overview.html", await _overview_context(session, status, q)
    )
    # обновление от пользователя меняет адресную строку; poll (его триггер —
    # сам контейнер #overview) не должен спамить историю браузера
    if request.headers.get("HX-Trigger") != "overview":
        response.headers["HX-Push-Url"] = _page_url(status, q)
    return response
