"""Бригады: коллекция вложена в объект, операции над бригадой — по её id."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, PathID, SessionDep, office_only
from app.api.sites import ensure_site_access, get_site_or_404
from app.models import Crew
from app.schemas.crews import CrewCreate, CrewOut, CrewUpdate

router = APIRouter(tags=["crews"])


async def _get_crew_or_404(session: AsyncSession, crew_id: int) -> Crew:
    crew = await session.get(Crew, crew_id)
    if crew is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Бригада не найдена")
    return crew


@router.post(
    "/sites/{site_id}/crews", status_code=status.HTTP_201_CREATED, dependencies=[office_only]
)
async def create_crew(site_id: PathID, data: CrewCreate, session: SessionDep) -> CrewOut:
    """Создать бригаду на объекте."""
    site = await get_site_or_404(session, site_id)
    crew = Crew(site_id=site.id, **data.model_dump())
    session.add(crew)
    try:
        await session.commit()
    # объект могли удалить между проверкой и вставкой — FK, для клиента это 404
    except IntegrityError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден") from None
    return CrewOut.model_validate(crew)


@router.get("/sites/{site_id}/crews")
async def list_crews(site_id: PathID, session: SessionDep, user: CurrentUser) -> list[CrewOut]:
    """Бригады объекта по возрастанию id; прорабу доступны только его объекты."""
    site = await get_site_or_404(session, site_id)
    ensure_site_access(site, user)
    crews = await session.scalars(select(Crew).where(Crew.site_id == site.id).order_by(Crew.id))
    return [CrewOut.model_validate(crew) for crew in crews]


@router.patch("/crews/{crew_id}", dependencies=[office_only])
async def update_crew(crew_id: PathID, data: CrewUpdate, session: SessionDep) -> CrewOut:
    """Частичное обновление бригады."""
    crew = await _get_crew_or_404(session, crew_id)
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(crew, name, value)
    await session.commit()
    return CrewOut.model_validate(crew)


@router.delete(
    "/crews/{crew_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[office_only]
)
async def delete_crew(crew_id: PathID, session: SessionDep) -> None:
    """Удалить бригаду."""
    crew = await _get_crew_or_404(session, crew_id)
    await session.delete(crew)
    await session.commit()
