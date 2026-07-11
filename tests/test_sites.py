"""Тесты CRUD стройплощадок и назначения прорабов."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConstructionSite, User, UserRole, site_assignments
from tests.conftest import SiteFactory, UserFactory, auth_headers

SITE_JSON = {
    "name": "ЖК Солнечный",
    "address": "ул. Ленина, 1",
    "start_date": "2026-02-02",
    "planned_end_date": "2027-08-31",
}


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(UserRole.FOREMAN)


class TestAccess:
    async def test_no_token_401(self, client: AsyncClient):
        response = await client.get("/sites")

        assert response.status_code == 401

    async def test_foreman_cannot_create_403(self, client: AsyncClient, foreman: User):
        response = await client.post("/sites", json=SITE_JSON, headers=auth_headers(foreman))

        assert response.status_code == 403

    async def test_foreman_cannot_update_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.patch(
            f"/sites/{site.id}", json={"name": "Другое"}, headers=auth_headers(foreman)
        )

        assert response.status_code == 403

    async def test_foreman_cannot_assign_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/foremen",
            json={"user_id": foreman.id},
            headers=auth_headers(foreman),
        )

        assert response.status_code == 403


class TestCreateSite:
    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
    async def test_office_creates_201(
        self, client: AsyncClient, make_user: UserFactory, role: UserRole
    ):
        user = await make_user(role)

        response = await client.post("/sites", json=SITE_JSON, headers=auth_headers(user))

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "ЖК Солнечный"
        assert body["status"] == "active"
        assert body["foremen"] == []

    async def test_end_before_start_422(self, client: AsyncClient, manager: User):
        response = await client.post(
            "/sites",
            json={**SITE_JSON, "planned_end_date": "2026-01-01"},
            headers=auth_headers(manager),
        )

        assert response.status_code == 422


class TestListSites:
    async def test_manager_sees_all(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        await make_site()
        await make_site()

        response = await client.get("/sites", headers=auth_headers(manager))

        assert response.status_code == 200
        ids = [site["id"] for site in response.json()]
        assert len(ids) == 2
        assert ids == sorted(ids)

    async def test_foreman_sees_only_assigned(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        mine = await make_site(foremen=[foreman])
        await make_site()

        response = await client.get("/sites", headers=auth_headers(foreman))

        assert response.status_code == 200
        assert [site["id"] for site in response.json()] == [mine.id]


class TestGetSite:
    async def test_manager_gets_any_with_foremen(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.get(f"/sites/{site.id}", headers=auth_headers(manager))

        assert response.status_code == 200
        assert [f["id"] for f in response.json()["foremen"]] == [foreman.id]

    async def test_foreman_gets_own(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.get(f"/sites/{site.id}", headers=auth_headers(foreman))

        assert response.status_code == 200

    async def test_foreman_foreign_site_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}", headers=auth_headers(foreman))

        assert response.status_code == 403

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.get("/sites/1000000", headers=auth_headers(manager))

        assert response.status_code == 404

    async def test_id_out_of_int_range_422(self, client: AsyncClient, manager: User):
        response = await client.get("/sites/99999999999999999999", headers=auth_headers(manager))

        assert response.status_code == 422

    async def test_foremen_payload_without_contacts(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        """Состав объекта видят и прорабы — контакты коллег наружу не отдаём."""
        site = await make_site(foremen=[foreman])

        response = await client.get(f"/sites/{site.id}", headers=auth_headers(manager))

        assert set(response.json()["foremen"][0]) == {"id", "full_name"}


class TestUpdateSite:
    async def test_partial_update_keeps_other_fields(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        site = await make_site(name="ЖК Первый")

        response = await client.patch(
            f"/sites/{site.id}", json={"status": "completed"}, headers=auth_headers(manager)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["name"] == "ЖК Первый"

    async def test_end_before_start_400(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.patch(
            f"/sites/{site.id}",
            json={"planned_end_date": "2020-01-01"},
            headers=auth_headers(manager),
        )

        assert response.status_code == 400

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/sites/1000000", json={"name": "Никакой"}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_null_field_422(self, client: AsyncClient, manager: User, make_site: SiteFactory):
        """У объекта нет очищаемых полей — явный null не превращается в 500 на NOT NULL."""
        site = await make_site()

        response = await client.patch(
            f"/sites/{site.id}", json={"name": None}, headers=auth_headers(manager)
        )

        assert response.status_code == 422


class TestDeleteSite:
    async def test_delete_cascades_assignments_keeps_users(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_site: SiteFactory,
        db_session: AsyncSession,
    ):
        site = await make_site(foremen=[foreman])

        response = await client.delete(f"/sites/{site.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        gone = await client.get(f"/sites/{site.id}", headers=auth_headers(manager))
        assert gone.status_code == 404
        assignments = (await db_session.execute(select(site_assignments))).all()
        assert assignments == []
        alive = await db_session.scalar(select(User).where(User.id == foreman.id))
        assert alive is not None


class TestAssignments:
    async def test_assign_foreman_204(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/foremen",
            json={"user_id": foreman.id},
            headers=auth_headers(manager),
        )

        assert response.status_code == 204
        detail = await client.get(f"/sites/{site.id}", headers=auth_headers(manager))
        assert [f["id"] for f in detail.json()["foremen"]] == [foreman.id]

    async def test_assign_twice_409(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.post(
            f"/sites/{site.id}/foremen",
            json={"user_id": foreman.id},
            headers=auth_headers(manager),
        )

        assert response.status_code == 409

    async def test_assign_non_foreman_400(
        self, client: AsyncClient, manager: User, make_user: UserFactory, make_site: SiteFactory
    ):
        site = await make_site()
        other_manager = await make_user(UserRole.MANAGER)

        response = await client.post(
            f"/sites/{site.id}/foremen",
            json={"user_id": other_manager.id},
            headers=auth_headers(manager),
        )

        assert response.status_code == 400

    async def test_assign_inactive_foreman_400(
        self,
        client: AsyncClient,
        manager: User,
        make_user: UserFactory,
        make_site: SiteFactory,
        db_session: AsyncSession,
    ):
        site = await make_site()
        foreman = await make_user(UserRole.FOREMAN)
        foreman.is_active = False
        await db_session.commit()

        response = await client.post(
            f"/sites/{site.id}/foremen",
            json={"user_id": foreman.id},
            headers=auth_headers(manager),
        )

        assert response.status_code == 400

    async def test_assign_unknown_user_404(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/foremen", json={"user_id": 1000000}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_assign_to_unknown_site_404(
        self, client: AsyncClient, manager: User, foreman: User
    ):
        response = await client.post(
            "/sites/1000000/foremen", json={"user_id": foreman.id}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_unassign_204(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.delete(
            f"/sites/{site.id}/foremen/{foreman.id}", headers=auth_headers(manager)
        )

        assert response.status_code == 204
        detail = await client.get(f"/sites/{site.id}", headers=auth_headers(manager))
        assert detail.json()["foremen"] == []

    async def test_unassign_not_assigned_404(
        self, client: AsyncClient, manager: User, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.delete(
            f"/sites/{site.id}/foremen/{foreman.id}", headers=auth_headers(manager)
        )

        assert response.status_code == 404


class TestDbConstraints:
    async def test_db_rejects_end_before_start(self, db_session: AsyncSession):
        """API проверяет инвариант дат сам, но последний рубеж — CHECK в БД."""
        site = ConstructionSite(
            name="ЖК Невозможный",
            address="ул. Парадоксальная, 1",
            start_date=date(2027, 1, 1),
            planned_end_date=date(2026, 1, 1),
            foremen=[],
        )
        db_session.add(site)

        with pytest.raises(IntegrityError):
            await db_session.commit()
