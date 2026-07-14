"""Тесты справочника материалов."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyReport, ReportMaterialUsage, User, UserRole
from tests.conftest import DeliveryFactory, MaterialFactory, SiteFactory, UserFactory, auth_headers


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(UserRole.FOREMAN)


class TestAccess:
    async def test_no_token_401(self, client: AsyncClient):
        response = await client.get("/materials")

        assert response.status_code == 401

    async def test_foreman_reads_200(
        self, client: AsyncClient, foreman: User, make_material: MaterialFactory
    ):
        # справочник открыт прорабу: в отчётах он указывает расход материалов
        await make_material()

        response = await client.get("/materials", headers=auth_headers(foreman))

        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_foreman_cannot_create_403(self, client: AsyncClient, foreman: User):
        response = await client.post(
            "/materials", json={"name": "Цемент М500", "unit": "т"}, headers=auth_headers(foreman)
        )

        assert response.status_code == 403

    async def test_foreman_cannot_update_403(
        self, client: AsyncClient, foreman: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.patch(
            f"/materials/{material.id}", json={"unit": "кг"}, headers=auth_headers(foreman)
        )

        assert response.status_code == 403

    async def test_foreman_cannot_delete_403(
        self, client: AsyncClient, foreman: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.delete(f"/materials/{material.id}", headers=auth_headers(foreman))

        assert response.status_code == 403


class TestCreateMaterial:
    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
    async def test_office_creates_201(
        self, client: AsyncClient, make_user: UserFactory, role: UserRole
    ):
        user = await make_user(role)

        response = await client.post(
            "/materials", json={"name": "Цемент М500", "unit": "т"}, headers=auth_headers(user)
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Цемент М500"
        assert body["unit"] == "т"

    async def test_duplicate_name_409(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        await make_material(name="Цемент М500")

        response = await client.post(
            "/materials", json={"name": "Цемент М500", "unit": "кг"}, headers=auth_headers(manager)
        )

        assert response.status_code == 409

    async def test_empty_name_422(self, client: AsyncClient, manager: User):
        response = await client.post(
            "/materials", json={"name": "", "unit": "т"}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_empty_unit_422(self, client: AsyncClient, manager: User):
        response = await client.post(
            "/materials", json={"name": "Цемент М500", "unit": ""}, headers=auth_headers(manager)
        )

        assert response.status_code == 422


class TestListMaterials:
    async def test_ordered_by_name(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        await make_material(name="Цемент М500")
        await make_material(name="Арматура А500С")
        await make_material(name="Бетон В25")

        response = await client.get("/materials", headers=auth_headers(manager))

        assert response.status_code == 200
        names = [material["name"] for material in response.json()]
        assert names == ["Арматура А500С", "Бетон В25", "Цемент М500"]

    async def test_empty_list(self, client: AsyncClient, manager: User):
        response = await client.get("/materials", headers=auth_headers(manager))

        assert response.status_code == 200
        assert response.json() == []


class TestUpdateMaterial:
    async def test_partial_update_keeps_other_fields(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        material = await make_material(name="Цемент М500", unit="т")

        response = await client.patch(
            f"/materials/{material.id}", json={"unit": "кг"}, headers=auth_headers(manager)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["unit"] == "кг"
        assert body["name"] == "Цемент М500"

    async def test_rename_to_taken_name_409(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        await make_material(name="Цемент М500")
        material = await make_material(name="Бетон В25")

        response = await client.patch(
            f"/materials/{material.id}",
            json={"name": "Цемент М500"},
            headers=auth_headers(manager),
        )

        assert response.status_code == 409

    async def test_null_field_422(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.patch(
            f"/materials/{material.id}", json={"name": None}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_empty_name_422(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.patch(
            f"/materials/{material.id}", json={"name": ""}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/materials/1000000", json={"unit": "кг"}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_id_out_of_int_range_422(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/materials/99999999999999999999", json={"unit": "кг"}, headers=auth_headers(manager)
        )

        assert response.status_code == 422


class TestDeleteMaterial:
    async def test_delete_204_then_gone(
        self, client: AsyncClient, manager: User, make_material: MaterialFactory
    ):
        material = await make_material()

        response = await client.delete(f"/materials/{material.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        remaining = await client.get("/materials", headers=auth_headers(manager))
        assert remaining.json() == []

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.delete("/materials/1000000", headers=auth_headers(manager))

        assert response.status_code == 404

    async def test_referenced_by_delivery_409(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        material = await make_material()
        await make_delivery(await make_site(), material)

        response = await client.delete(f"/materials/{material.id}", headers=auth_headers(manager))

        assert response.status_code == 409

    async def test_referenced_by_report_usage_409(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        site = await make_site(foremen=[foreman])
        material = await make_material()
        report = DailyReport(
            site_id=site.id,
            foreman_id=foreman.id,
            report_date=date(2026, 7, 1),
            work_description="Заливка перекрытия",
            workers_count=10,
        )
        db_session.add(report)
        await db_session.commit()
        db_session.add(
            ReportMaterialUsage(
                report_id=report.id, material_id=material.id, quantity=Decimal("1.5")
            )
        )
        await db_session.commit()

        response = await client.delete(f"/materials/{material.id}", headers=auth_headers(manager))

        assert response.status_code == 409
