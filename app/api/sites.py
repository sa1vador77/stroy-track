"""Стройплощадки: CRUD и назначение прорабов."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select, select

from app.api.deps import CurrentUser, PathID, SessionDep, require_roles
from app.models import ConstructionSite, User, UserRole, site_assignments
from app.schemas.sites import ForemanAssignment, SiteCreate, SiteOut, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])

# читают объекты все роли (прораб — только свои), управляет офис
office_only = Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN))


def _site_query() -> Select[tuple[ConstructionSite]]:
    # прорабы нужны в каждом ответе; selectinload — вторым запросом,
    # ленивые дозагрузки в asyncio запрещены
    return select(ConstructionSite).options(selectinload(ConstructionSite.foremen))


async def _get_site_or_404(session: AsyncSession, site_id: int) -> ConstructionSite:
    site = await session.scalar(_site_query().where(ConstructionSite.id == site_id))
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
    return site


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[office_only])
async def create_site(data: SiteCreate, session: SessionDep) -> SiteOut:
    """Создать объект."""
    # foremen=[] инициализирует коллекцию: у нового объекта прорабов ещё нет,
    # а обращение к незагруженному relationship при сериализации упало бы
    site = ConstructionSite(**data.model_dump(), foremen=[])
    session.add(site)
    await session.commit()
    return SiteOut.model_validate(site)


@router.get("")
async def list_sites(session: SessionDep, user: CurrentUser) -> list[SiteOut]:
    """Все объекты по возрастанию id; прораб видит только назначенные ему."""
    query = _site_query().order_by(ConstructionSite.id)
    if user.role == UserRole.FOREMAN:
        query = query.join(site_assignments).where(site_assignments.c.user_id == user.id)
    sites = await session.scalars(query)
    return [SiteOut.model_validate(site) for site in sites]


@router.get("/{site_id}")
async def get_site(site_id: PathID, session: SessionDep, user: CurrentUser) -> SiteOut:
    """Объект по id; прорабу доступны только его объекты."""
    site = await _get_site_or_404(session, site_id)
    if user.role == UserRole.FOREMAN and user.id not in {f.id for f in site.foremen}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Объект вам не назначен")
    return SiteOut.model_validate(site)


@router.patch("/{site_id}", dependencies=[office_only])
async def update_site(site_id: PathID, data: SiteUpdate, session: SessionDep) -> SiteOut:
    """Частичное обновление объекта."""
    site = await _get_site_or_404(session, site_id)
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(site, name, value)
    # инвариант дат проверяется по итоговому состоянию: поля могли прийти поодиночке
    if site.planned_end_date < site.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Плановое окончание раньше начала работ")
    await session.commit()
    return SiteOut.model_validate(site)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[office_only])
async def delete_site(site_id: PathID, session: SessionDep) -> None:
    """Удалить объект; назначения, бригады, поставки и отчёты удаляет каскад в БД."""
    site = await _get_site_or_404(session, site_id)
    await session.delete(site)
    await session.commit()


@router.post(
    "/{site_id}/foremen", status_code=status.HTTP_204_NO_CONTENT, dependencies=[office_only]
)
async def assign_foreman(site_id: PathID, data: ForemanAssignment, session: SessionDep) -> None:
    """Назначить прораба на объект."""
    site = await _get_site_or_404(session, site_id)
    foreman = await session.get(User, data.user_id)
    if foreman is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if foreman.role != UserRole.FOREMAN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Назначать на объект можно только прораба")
    if not foreman.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Прораб деактивирован")
    if any(f.id == foreman.id for f in site.foremen):
        raise HTTPException(status.HTTP_409_CONFLICT, "Прораб уже назначен на этот объект")
    site.foremen.append(foreman)
    try:
        await session.commit()
    # два одновременных назначения: проверку выше прошли оба, второго останавливает PK
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Прораб уже назначен на этот объект"
        ) from None


@router.delete(
    "/{site_id}/foremen/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[office_only],
)
async def unassign_foreman(site_id: PathID, user_id: PathID, session: SessionDep) -> None:
    """Снять прораба с объекта."""
    site = await _get_site_or_404(session, site_id)
    foreman = next((f for f in site.foremen if f.id == user_id), None)
    if foreman is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Назначение не найдено")
    site.foremen.remove(foreman)
    await session.commit()
