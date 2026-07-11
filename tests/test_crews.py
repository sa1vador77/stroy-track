"""Тесты CRUD бригад."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Crew, User, UserRole
from tests.conftest import CrewFactory, SiteFactory, UserFactory, auth_headers


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(UserRole.FOREMAN)


class TestAccess:
    async def test_no_token_401(self, client: AsyncClient, make_site: SiteFactory):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/crews")

        assert response.status_code == 401

    async def test_foreman_cannot_create_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site(foremen=[foreman])

        response = await client.post(
            f"/sites/{site.id}/crews",
            json={"name": "Монолитчики", "size": 12},
            headers=auth_headers(foreman),
        )

        assert response.status_code == 403

    async def test_foreman_cannot_update_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site(foremen=[foreman]))

        response = await client.patch(
            f"/crews/{crew.id}", json={"size": 5}, headers=auth_headers(foreman)
        )

        assert response.status_code == 403

    async def test_foreman_cannot_delete_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site(foremen=[foreman]))

        response = await client.delete(f"/crews/{crew.id}", headers=auth_headers(foreman))

        assert response.status_code == 403


class TestCreateCrew:
    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
    async def test_office_creates_201(
        self, client: AsyncClient, make_user: UserFactory, make_site: SiteFactory, role: UserRole
    ):
        user = await make_user(role)
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/crews",
            json={"name": "Монолитчики", "size": 12},
            headers=auth_headers(user),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Монолитчики"
        assert body["size"] == 12
        assert body["site_id"] == site.id

    async def test_unknown_site_404(self, client: AsyncClient, manager: User):
        response = await client.post(
            "/sites/1000000/crews",
            json={"name": "Монолитчики", "size": 12},
            headers=auth_headers(manager),
        )

        assert response.status_code == 404

    async def test_zero_size_422(self, client: AsyncClient, manager: User, make_site: SiteFactory):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/crews",
            json={"name": "Пустая", "size": 0},
            headers=auth_headers(manager),
        )

        assert response.status_code == 422

    async def test_empty_name_422(self, client: AsyncClient, manager: User, make_site: SiteFactory):
        site = await make_site()

        response = await client.post(
            f"/sites/{site.id}/crews",
            json={"name": "", "size": 5},
            headers=auth_headers(manager),
        )

        assert response.status_code == 422


class TestListCrews:
    async def test_manager_sees_site_crews_ordered(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        site = await make_site()
        other = await make_site()
        first = await make_crew(site)
        second = await make_crew(site)
        await make_crew(other)

        response = await client.get(f"/sites/{site.id}/crews", headers=auth_headers(manager))

        assert response.status_code == 200
        assert [crew["id"] for crew in response.json()] == [first.id, second.id]

    async def test_site_without_crews_empty_list(
        self, client: AsyncClient, manager: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/crews", headers=auth_headers(manager))

        assert response.status_code == 200
        assert response.json() == []

    async def test_foreman_sees_own_site_crews(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        site = await make_site(foremen=[foreman])
        await make_crew(site)

        response = await client.get(f"/sites/{site.id}/crews", headers=auth_headers(foreman))

        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_foreman_foreign_site_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/crews", headers=auth_headers(foreman))

        assert response.status_code == 403

    async def test_unknown_site_404(self, client: AsyncClient, manager: User):
        response = await client.get("/sites/1000000/crews", headers=auth_headers(manager))

        assert response.status_code == 404


class TestUpdateCrew:
    async def test_partial_update_keeps_other_fields(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site(), name="Отделочники", size=7)

        response = await client.patch(
            f"/crews/{crew.id}", json={"size": 9}, headers=auth_headers(manager)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["size"] == 9
        assert body["name"] == "Отделочники"

    async def test_null_field_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site())

        response = await client.patch(
            f"/crews/{crew.id}", json={"name": None}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_zero_size_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site())

        response = await client.patch(
            f"/crews/{crew.id}", json={"size": 0}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_empty_name_422(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        crew = await make_crew(await make_site())

        response = await client.patch(
            f"/crews/{crew.id}", json={"name": ""}, headers=auth_headers(manager)
        )

        assert response.status_code == 422

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/crews/1000000", json={"size": 3}, headers=auth_headers(manager)
        )

        assert response.status_code == 404

    async def test_id_out_of_int_range_422(self, client: AsyncClient, manager: User):
        response = await client.patch(
            "/crews/99999999999999999999", json={"size": 3}, headers=auth_headers(manager)
        )

        assert response.status_code == 422


class TestDeleteCrew:
    async def test_delete_204_then_gone(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
    ):
        site = await make_site()
        crew = await make_crew(site)

        response = await client.delete(f"/crews/{crew.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        remaining = await client.get(f"/sites/{site.id}/crews", headers=auth_headers(manager))
        assert remaining.json() == []

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.delete("/crews/1000000", headers=auth_headers(manager))

        assert response.status_code == 404

    async def test_site_delete_cascades_crews(
        self,
        client: AsyncClient,
        manager: User,
        make_site: SiteFactory,
        make_crew: CrewFactory,
        db_session: AsyncSession,
    ):
        site = await make_site()
        await make_crew(site)

        response = await client.delete(f"/sites/{site.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        crews = (await db_session.scalars(select(Crew))).all()
        assert crews == []
