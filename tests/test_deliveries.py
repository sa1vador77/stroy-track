"""Тесты CRUD поставок материалов."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deliveries import _integrity_404
from app.models import MaterialDelivery, User, UserRole
from tests.conftest import (
    DeliveryFactory,
    MaterialFactory,
    SiteFactory,
    UserFactory,
    auth_headers,
)


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(UserRole.FOREMAN)


class TestAccess:
    async def test_no_token_401(self, client: AsyncClient, make_site: SiteFactory):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/deliveries")

        assert response.status_code == 401

    async def test_foreman_reads_own_site_200(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        site = await make_site(foremen=[foreman])
        await make_delivery(site, await make_material())

        response = await client.get(f"/sites/{site.id}/deliveries", headers=auth_headers(foreman))

        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_foreman_foreign_site_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/deliveries", headers=auth_headers(foreman))

        assert response.status_code == 403

    async def test_foreman_cannot_create_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
    ):
        site = await make_site(foremen=[foreman])
        material = await make_material()

        response = await client.post(
            f"/sites/{site.id}/deliveries",
            json={
                "material_id": material.id,
                "quantity": "2.5",
                "delivery_date": "2026-07-01",
                "supplier": "СтройБаза №1",
            },
            headers=auth_headers(foreman),
        )

        assert response.status_code == 403

    async def test_foreman_cannot_update_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(await make_site(foremen=[foreman]), await make_material())

        response = await client.patch(
            f"/deliveries/{delivery.id}", json={"quantity": "3"}, headers=auth_headers(foreman)
        )

        assert response.status_code == 403

    async def test_foreman_cannot_delete_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(await make_site(foremen=[foreman]), await make_material())

        response = await client.delete(f"/deliveries/{delivery.id}", headers=auth_headers(foreman))

        assert response.status_code == 403


class TestCreateDelivery:
    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
    async def test_office_creates_201(
        self,
        client: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        role: UserRole,
    ):
        user = await make_user(role)
        site = await make_site()
        material = await make_material()

        response = await client.post(
            f"/sites/{site.id}/deliveries",
            json={
                "material_id": material.id,
                "quantity": "2.5",
                "delivery_date": "2026-07-01",
                "supplier": "СтройБаза №1",
            },
            headers=auth_headers(user),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["site_id"] == site.id
        assert body["material_id"] == material.id
        # каноничный масштаб Numeric(12, 3): POST и GET отдают одно представление
        assert body["quantity"] == "2.500"
        assert body["delivery_date"] == "2026-07-01"
        assert body["supplier"] == "СтройБаза №1"

    async def test_unknown_site_404(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.post(
            "/sites/1000000/deliveries",
            json={
                "material_id": material.id,
                "quantity": "2.5",
                "delivery_date": "2026-07-01",
                "supplier": "СтройБаза №1",
            },
            headers=auth_headers(manager),
        )

        assert response.status_code == 404

    async def test_unknown_material_404(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/deliveries",
            json={
                "material_id": 1000000,
                "quantity": "2.5",
                "delivery_date": "2026-07-01",
                "supplier": "СтройБаза №1",
            },
            headers=auth_headers(manager),
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "quantity",
        [
            "0",  # CHECK quantity > 0
            "-1",
            "0.0001",  # четвёртый знак не влезает в Numeric(12, 3)
            "1234567890.5",  # 10 цифр в целой части при потолке 12 - 3 = 9
            "9999999999.999",  # больше 12 цифр всего
        ],
    )
    async def test_bad_quantity_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        quantity: str,
    ):
        site = await make_site()
        material = await make_material()

        response = await client.post(
            f"/sites/{site.id}/deliveries",
            json={
                "material_id": material.id,
                "quantity": quantity,
                "delivery_date": "2026-07-01",
                "supplier": "СтройБаза №1",
            },
            headers=auth_headers(manager),
        )

        assert response.status_code == 422

    async def test_empty_supplier_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
    ):
        site = await make_site()
        material = await make_material()

        response = await client.post(
            f"/sites/{site.id}/deliveries",
            json={
                "material_id": material.id,
                "quantity": "2.5",
                "delivery_date": "2026-07-01",
                "supplier": "",
            },
            headers=auth_headers(manager),
        )

        assert response.status_code == 422


class TestListDeliveries:
    async def test_ordered_by_date_then_id(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        site = await make_site()
        material = await make_material()
        later = await make_delivery(site, material, delivery_date=date(2026, 7, 5))
        earlier = await make_delivery(site, material, delivery_date=date(2026, 7, 1))
        same_day = await make_delivery(site, material, delivery_date=date(2026, 7, 5))

        response = await client.get(f"/sites/{site.id}/deliveries", headers=auth_headers(manager))

        assert response.status_code == 200
        assert [d["id"] for d in response.json()] == [earlier.id, later.id, same_day.id]

    async def test_other_site_deliveries_not_listed(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        site = await make_site()
        material = await make_material()
        await make_delivery(await make_site(), material)

        response = await client.get(f"/sites/{site.id}/deliveries", headers=auth_headers(manager))

        assert response.status_code == 200
        assert response.json() == []

    async def test_unknown_site_404(self, client: AsyncClient, manager: User):
        response = await client.get("/sites/1000000/deliveries", headers=auth_headers(manager))

        assert response.status_code == 404


class TestUpdateDelivery:
    async def test_partial_update_keeps_other_fields(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(
            await make_site(),
            await make_material(),
            quantity=Decimal("10"),
            supplier="СтройБаза №1",
        )

        response = await client.patch(
            f"/deliveries/{delivery.id}", json={"quantity": "7.5"}, headers=auth_headers(manager)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["quantity"] == "7.500"
        assert body["supplier"] == "СтройБаза №1"

    async def test_change_material(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(await make_site(), await make_material())
        other = await make_material()

        response = await client.patch(
            f"/deliveries/{delivery.id}",
            json={"material_id": other.id},
            headers=auth_headers(manager),
        )

        assert response.status_code == 200
        assert response.json()["material_id"] == other.id

    async def test_unknown_material_404(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(await make_site(), await make_material())

        response = await client.patch(
            f"/deliveries/{delivery.id}",
            json={"material_id": 1000000},
            headers=auth_headers(manager),
        )

        assert response.status_code == 404

    async def test_null_field_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        delivery = await make_delivery(await make_site(), await make_material())

        response = await client.patch(
            f"/deliveries/{delivery.id}", json={"quantity": None}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/deliveries/1000000", json={"quantity": "1"}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_id_out_of_int_range_422(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/deliveries/99999999999999999999",
            json={"quantity": "1"},
            headers=auth_headers(manager),
        )

        assert response.status_code == 422


class TestDeleteDelivery:
    async def test_delete_204_then_gone(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        site = await make_site()
        delivery = await make_delivery(site, await make_material())

        response = await client.delete(f"/deliveries/{delivery.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        remaining = await client.get(f"/sites/{site.id}/deliveries", headers=auth_headers(manager))
        assert remaining.json() == []

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.delete("/deliveries/1000000", headers=auth_headers(manager))

        assert response.status_code == 404

    async def test_site_delete_cascades_deliveries(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
        db_session: AsyncSession,
    ):
        site = await make_site()
        await make_delivery(site, await make_material())

        response = await client.delete(f"/sites/{site.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        deliveries = (await db_session.scalars(select(MaterialDelivery))).all()
        assert deliveries == []


def _fk_violation(constraint: str) -> IntegrityError:
    orig = Exception(f'нарушает ограничение внешнего ключа "{constraint}"')
    return IntegrityError("INSERT INTO material_deliveries ...", {}, orig)


class TestIntegrity404Mapping:
    """Ветки _integrity_404 достижимы только в гонке с удалением — проверяем функцию напрямую."""

    def test_material_fk_maps_to_material(self):
        exc = _fk_violation("fk_material_deliveries_material_id_materials")

        assert _integrity_404(exc).detail == "Материал не найден"

    def test_site_fk_maps_to_site(self):
        exc = _fk_violation("fk_material_deliveries_site_id_construction_sites")

        assert _integrity_404(exc).detail == "Объект не найден"
