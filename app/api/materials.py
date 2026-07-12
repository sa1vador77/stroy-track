"""Справочник материалов: читают все аутентифицированные, изменяет офис."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PathID, SessionDep, get_current_user, office_only
from app.models import Material
from app.schemas.materials import MaterialCreate, MaterialOut, MaterialUpdate

router = APIRouter(prefix="/materials", tags=["materials"])


async def _get_material_or_404(session: AsyncSession, material_id: int) -> Material:
    material = await session.get(Material, material_id)
    if material is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")
    return material


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[office_only])
async def create_material(data: MaterialCreate, session: SessionDep) -> MaterialOut:
    """Добавить материал; название уникально."""
    material = Material(**data.model_dump())
    session.add(material)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Материал с таким названием уже есть"
        ) from None
    return MaterialOut.model_validate(material)


@router.get("", dependencies=[Depends(get_current_user)])
async def list_materials(session: SessionDep) -> list[MaterialOut]:
    """Весь справочник по алфавиту; прорабу нужен для расхода материалов в отчётах."""
    materials = await session.scalars(select(Material).order_by(Material.name))
    return [MaterialOut.model_validate(material) for material in materials]


@router.patch("/{material_id}", dependencies=[office_only])
async def update_material(
    material_id: PathID, data: MaterialUpdate, session: SessionDep
) -> MaterialOut:
    """Частичное обновление материала."""
    material = await _get_material_or_404(session, material_id)
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(material, name, value)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Материал с таким названием уже есть"
        ) from None
    return MaterialOut.model_validate(material)


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[office_only])
async def delete_material(material_id: PathID, session: SessionDep) -> None:
    """Удалить материал; используемый в поставках или отчётах защищён от удаления."""
    material = await _get_material_or_404(session, material_id)
    await session.delete(material)
    try:
        await session.commit()
    # FK RESTRICT: история поставок и отчётов важнее записи справочника
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Материал используется в поставках или отчётах"
        ) from None
