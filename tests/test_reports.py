"""Тесты чтения отчётов прорабов."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailyReport, ReportMaterialUsage, ReportPhoto, User, UserRole
from tests.conftest import (
    MaterialFactory,
    ReportFactory,
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

        response = await client.get(f"/sites/{site.id}/reports")

        assert response.status_code == 401

    async def test_no_token_item_401(self, client: AsyncClient):
        response = await client.get("/reports/1")

        assert response.status_code == 401

    async def test_foreman_reads_own_site_200(
        self,
        client: AsyncClient,
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        site = await make_site(foremen=[foreman])
        await make_report(site, foreman)

        response = await client.get(f"/sites/{site.id}/reports", headers=auth_headers(foreman))

        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_foreman_reads_colleague_report_200(
        self,
        client: AsyncClient,
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        # доступ по объекту, а не по автору: прорабы одного объекта видят отчёты друг друга
        colleague = await make_user()
        site = await make_site(foremen=[foreman, colleague])
        report = await make_report(site, colleague)

        response = await client.get(f"/reports/{report.id}", headers=auth_headers(foreman))

        assert response.status_code == 200

    async def test_foreman_foreign_site_403(
        self, client: AsyncClient, foreman: User, make_site: SiteFactory
    ):
        site = await make_site()

        response = await client.get(f"/sites/{site.id}/reports", headers=auth_headers(foreman))

        assert response.status_code == 403

    async def test_foreman_foreign_report_403(
        self,
        client: AsyncClient,
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        author = await make_user()
        report = await make_report(await make_site(foremen=[author]), author)

        response = await client.get(f"/reports/{report.id}", headers=auth_headers(foreman))

        assert response.status_code == 403


class TestListReports:
    async def test_ordered_by_date_then_id(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        site = await make_site()
        colleague = await make_user()
        later = await make_report(site, foreman, report_date=date(2026, 7, 5))
        earlier = await make_report(site, foreman, report_date=date(2026, 7, 1))
        # тот же день, но другой автор: пара (site, foreman, date) уникальна
        same_day = await make_report(site, colleague, report_date=date(2026, 7, 5))

        response = await client.get(f"/sites/{site.id}/reports", headers=auth_headers(manager))

        assert response.status_code == 200
        assert [r["id"] for r in response.json()] == [earlier.id, later.id, same_day.id]

    async def test_other_site_reports_not_listed(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        site = await make_site()
        await make_report(await make_site(), foreman)

        response = await client.get(f"/sites/{site.id}/reports", headers=auth_headers(manager))

        assert response.status_code == 200
        assert response.json() == []

    async def test_unknown_site_404(self, client: AsyncClient, manager: User):
        response = await client.get("/sites/1000000/reports", headers=auth_headers(manager))

        assert response.status_code == 404


class TestGetReport:
    async def test_full_payload(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_report: ReportFactory,
        db_session: AsyncSession,
    ):
        site = await make_site()
        material = await make_material()
        report = await make_report(site, foreman)
        photo = ReportPhoto(file_path="reports/2026-07-01/1.jpg")
        usage = ReportMaterialUsage(material_id=material.id, quantity=Decimal("2.5"))
        report.photos.append(photo)
        report.material_usages.append(usage)
        await db_session.commit()
        report_id = report.id
        # у объекта из фабрики коллекции уже загружены; сбрасываем состояние,
        # чтобы проверить selectinload в эндпоинте, а не артефакт identity map
        db_session.expire(report)

        response = await client.get(f"/reports/{report_id}", headers=auth_headers(manager))

        assert response.status_code == 200
        body = response.json()
        assert body["site_id"] == site.id
        assert body["foreman_id"] == foreman.id
        assert body["report_date"] == "2026-07-01"
        assert body["work_description"] == "Заливка фундамента"
        assert body["workers_count"] == 8
        assert body["created_at"] is not None
        assert body["photos"] == [{"id": photo.id, "file_path": "reports/2026-07-01/1.jpg"}]
        # масштаб 3 даёт сама колонка NUMERIC(12, 3): записали "2.5", из БД пришло "2.500"
        assert body["material_usages"] == [
            {"id": usage.id, "material_id": material.id, "quantity": "2.500"}
        ]

    @pytest.mark.parametrize("role", [UserRole.MANAGER, UserRole.ADMIN])
    async def test_office_reads_200(
        self,
        client: AsyncClient,
        make_user: UserFactory,
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
        role: UserRole,
    ):
        user = await make_user(role)
        report = await make_report(await make_site(), foreman)

        response = await client.get(f"/reports/{report.id}", headers=auth_headers(user))

        assert response.status_code == 200

    async def test_unknown_id_404(self, client: AsyncClient, manager: User):
        response = await client.get("/reports/1000000", headers=auth_headers(manager))

        assert response.status_code == 404

    async def test_id_out_of_int_range_422(self, client: AsyncClient, manager: User):
        response = await client.get("/reports/99999999999999999999", headers=auth_headers(manager))

        assert response.status_code == 422


class TestSiteCascade:
    async def test_site_delete_cascades_reports(
        self,
        client: AsyncClient,
        manager: User,
        foreman: User,
        make_site: SiteFactory,
        make_material: MaterialFactory,
        make_report: ReportFactory,
        db_session: AsyncSession,
    ):
        """Удаление объекта уносит отчёт вместе с фото и расходом — каскады в БД."""
        site = await make_site()
        report = await make_report(site, foreman)
        report.photos.append(ReportPhoto(file_path="reports/2026-07-01/1.jpg"))
        report.material_usages.append(
            ReportMaterialUsage(material_id=(await make_material()).id, quantity=Decimal("1"))
        )
        await db_session.commit()

        response = await client.delete(f"/sites/{site.id}", headers=auth_headers(manager))

        assert response.status_code == 204
        assert (await db_session.scalars(select(DailyReport))).all() == []
        assert (await db_session.scalars(select(ReportPhoto))).all() == []
        assert (await db_session.scalars(select(ReportMaterialUsage))).all() == []
