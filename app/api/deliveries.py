"""Поставки материалов: коллекция вложена в объект, операции над поставкой — по её id."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, PathID, SessionDep, office_only
from app.api.sites import ensure_site_access, get_site_or_404
from app.models import Material, MaterialDelivery
from app.schemas.deliveries import DeliveryCreate, DeliveryOut, DeliveryUpdate

router = APIRouter(tags=["deliveries"])


async def _get_delivery_or_404(session: AsyncSession, delivery_id: int) -> MaterialDelivery:
    delivery = await session.get(MaterialDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Поставка не найдена")
    return delivery


async def _ensure_material_exists(session: AsyncSession, material_id: int) -> None:
    if await session.get(Material, material_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")


def _integrity_404(exc: IntegrityError) -> HTTPException:
    # гонка с удалением объекта или материала: проверки прошли, запись остановил FK;
    # какой именно — говорит имя констрейнта из naming convention
    if "fk_material_deliveries_material_id_materials" in str(exc.orig):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")
    return HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")


@router.post(
    "/sites/{site_id}/deliveries", status_code=status.HTTP_201_CREATED, dependencies=[office_only]
)
async def create_delivery(
    site_id: PathID, data: DeliveryCreate, session: SessionDep
) -> DeliveryOut:
    """Зафиксировать поставку материала на объект."""
    site = await get_site_or_404(session, site_id)
    await _ensure_material_exists(session, data.material_id)
    delivery = MaterialDelivery(site_id=site.id, **data.model_dump())
    session.add(delivery)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise _integrity_404(exc) from None
    return DeliveryOut.model_validate(delivery)


@router.get("/sites/{site_id}/deliveries")
async def list_deliveries(
    site_id: PathID, session: SessionDep, user: CurrentUser
) -> list[DeliveryOut]:
    """Поставки объекта в хронологическом порядке; прорабу доступны только его объекты."""
    site = await get_site_or_404(session, site_id)
    ensure_site_access(site, user)
    deliveries = await session.scalars(
        select(MaterialDelivery)
        .where(MaterialDelivery.site_id == site.id)
        .order_by(MaterialDelivery.delivery_date, MaterialDelivery.id)
    )
    return [DeliveryOut.model_validate(delivery) for delivery in deliveries]


@router.patch("/deliveries/{delivery_id}", dependencies=[office_only])
async def update_delivery(
    delivery_id: PathID, data: DeliveryUpdate, session: SessionDep
) -> DeliveryOut:
    """Частичное обновление поставки."""
    delivery = await _get_delivery_or_404(session, delivery_id)
    fields = data.model_dump(exclude_unset=True)
    if "material_id" in fields:
        await _ensure_material_exists(session, fields["material_id"])
    for name, value in fields.items():
        setattr(delivery, name, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise _integrity_404(exc) from None
    return DeliveryOut.model_validate(delivery)


@router.delete(
    "/deliveries/{delivery_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[office_only]
)
async def delete_delivery(delivery_id: PathID, session: SessionDep) -> None:
    """Удалить поставку."""
    delivery = await _get_delivery_or_404(session, delivery_id)
    await session.delete(delivery)
    await session.commit()
