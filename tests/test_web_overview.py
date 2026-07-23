"""Тесты обзора дашборда: KPI, карточки, фильтр, поиск, partial для htmx."""

from datetime import timedelta

from httpx import AsyncClient

from app.core.clock import company_today
from app.models import SiteStatus
from tests.conftest import (
    DeliveryFactory,
    MaterialFactory,
    ReportFactory,
    SiteFactory,
    UserFactory,
)


class TestKpi:
    async def test_company_wide_numbers(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
        make_material: MaterialFactory,
        make_delivery: DeliveryFactory,
    ):
        today = company_today()
        submitted = await make_user(telegram_id=1)
        missing = await make_user(telegram_id=2)
        site = await make_site(foremen=[submitted, missing])
        # приостановленный объект не входит ни в «активные», ни в «ожидается»
        idle_foreman = await make_user(telegram_id=3)
        await make_site(status=SiteStatus.SUSPENDED, foremen=[idle_foreman])
        await make_report(site, submitted, report_date=today, workers_count=8)
        material = await make_material()
        await make_delivery(site, material, delivery_date=today)
        await make_delivery(site, material, delivery_date=today - timedelta(days=1))

        response = await office.get("/dashboard")

        assert response.status_code == 200
        assert 'id="kpi-active-sites">1<' in response.text
        assert 'id="kpi-reports">1 из 2<' in response.text
        assert 'id="kpi-workers">8<' in response.text
        assert 'id="kpi-deliveries">1<' in response.text

    async def test_deactivated_foreman_not_expected(
        self, office: AsyncClient, make_user: UserFactory, make_site: SiteFactory
    ):
        """Паритет с напоминаниями: деактивированному прорабу бот не пишет —
        дашборд не должен считать его «ожидаемым»."""
        active = await make_user(telegram_id=1)
        deactivated = await make_user(telegram_id=2)
        deactivated.is_active = False
        await make_site(foremen=[active, deactivated])

        response = await office.get("/dashboard")

        assert 'id="kpi-reports">0 из 1<' in response.text

    async def test_workers_follow_report_population(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        """«Сдал и деактивирован в тот же день»: отчёт выпадает из «сдано» —
        его рабочие выпадают из суммы тоже, иначе «0 отчётов, но 9 рабочих»."""
        active = await make_user(telegram_id=1)
        fired = await make_user(telegram_id=2)
        site = await make_site(foremen=[active, fired])
        await make_report(site, fired, report_date=company_today(), workers_count=9)
        fired.is_active = False

        response = await office.get("/dashboard")

        assert 'id="kpi-reports">0 из 1<' in response.text
        assert 'id="kpi-workers">0<' in response.text
        assert "Отчёты сегодня: 0 из 1" in response.text
        assert "Рабочих: 0" in response.text

    async def test_yesterday_report_not_counted(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        foreman = await make_user(telegram_id=1)
        site = await make_site(foremen=[foreman])
        await make_report(site, foreman, report_date=company_today() - timedelta(days=1))

        response = await office.get("/dashboard")

        assert 'id="kpi-reports">0 из 1<' in response.text
        assert 'id="kpi-workers">0<' in response.text


class TestCards:
    async def test_foreman_chips_show_submission(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        submitted = await make_user(telegram_id=1, full_name="Пётр Сдал")
        missing = await make_user(telegram_id=2, full_name="Иван Забыл")
        site = await make_site(foremen=[submitted, missing])
        await make_report(site, submitted, report_date=company_today())

        response = await office.get("/dashboard")

        assert 'bg-success-lt">Пётр Сдал<' in response.text
        assert 'bg-danger-lt">Иван Забыл<' in response.text

    async def test_site_without_foremen(self, office: AsyncClient, make_site: SiteFactory):
        await make_site()

        response = await office.get("/dashboard")

        assert "Прорабы не назначены" in response.text

    async def test_footer_counts_and_workers(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        today = company_today()
        first = await make_user(telegram_id=1)
        second = await make_user(telegram_id=2)
        site = await make_site(foremen=[first, second])
        await make_report(site, first, report_date=today, workers_count=5)
        await make_report(site, second, report_date=today, workers_count=7)

        response = await office.get("/dashboard")

        assert "Отчёты сегодня: 2 из 2" in response.text
        assert "Рабочих: 12" in response.text

    async def test_completed_site_neutral_chips(
        self, office: AsyncClient, make_user: UserFactory, make_site: SiteFactory
    ):
        """По завершённому объекту отчётов не ждут — чипы без красного и без счётчика."""
        foreman = await make_user(telegram_id=1, full_name="Олег Строгий")
        await make_site(status=SiteStatus.COMPLETED, foremen=[foreman])

        response = await office.get("/dashboard", params={"status": "completed"})

        assert 'bg-secondary-lt">Олег Строгий<' in response.text
        assert "Отчёты сегодня" not in response.text


class TestFilterAndSearch:
    async def test_default_shows_only_active(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="ЖК Северный")
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get("/dashboard")

        assert "ЖК Северный" in response.text
        assert "Склад Южный" not in response.text

    async def test_status_filter(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="ЖК Северный")
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get("/dashboard", params={"status": "completed"})

        assert "Склад Южный" in response.text
        assert "ЖК Северный" not in response.text

    async def test_all_statuses(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="ЖК Северный")
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get("/dashboard", params={"status": "all"})

        assert "ЖК Северный" in response.text
        assert "Склад Южный" in response.text

    async def test_unknown_status_falls_back_to_active(
        self, office: AsyncClient, make_site: SiteFactory
    ):
        """Мусор в query-параметре — не повод для 422 на странице."""
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get("/dashboard", params={"status": "hacked"})

        assert response.status_code == 200
        assert "Склад Южный" not in response.text

    async def test_search_case_insensitive(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="ЖК Северный")
        await make_site(name="Школа №7")

        response = await office.get("/dashboard", params={"q": "северный"})

        assert "ЖК Северный" in response.text
        assert "Школа №7" not in response.text

    async def test_search_percent_is_literal(self, office: AsyncClient, make_site: SiteFactory):
        """% в запросе — литерал, а не метасимвол LIKE."""
        await make_site(name="Готовность 50%")
        await make_site(name="Дом 100")

        response = await office.get("/dashboard", params={"q": "50%"})

        assert "Готовность 50%" in response.text
        assert "Дом 100" not in response.text

    async def test_search_underscore_is_literal(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="Дом_1")
        await make_site(name="Дом21")

        response = await office.get("/dashboard", params={"q": "м_1"})

        assert "Дом_1" in response.text
        assert "Дом21" not in response.text


class TestSorting:
    async def test_sites_with_missing_reports_first(
        self,
        office: AsyncClient,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        calm_foreman = await make_user(telegram_id=1)
        calm = await make_site(name="Альфа", foremen=[calm_foreman])
        await make_report(calm, calm_foreman, report_date=company_today())
        attention_foreman = await make_user(telegram_id=2)
        await make_site(name="Омега", foremen=[attention_foreman])

        response = await office.get("/dashboard")

        assert response.text.index("Омега") < response.text.index("Альфа")

    async def test_alphabetical_within_group(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="Бета")
        await make_site(name="Альфа")

        response = await office.get("/dashboard")

        assert response.text.index("Альфа") < response.text.index("Бета")


class TestOverviewPartial:
    async def test_fragment_with_push_url(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get(
            "/dashboard/overview",
            params={"status": "completed"},
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200
        # это фрагмент для вставки в #overview, а не самостоятельная страница
        assert "<html" not in response.text
        assert "Склад Южный" in response.text
        assert response.headers["hx-push-url"] == "/dashboard?status=completed"

    async def test_default_push_url_is_clean(self, office: AsyncClient):
        response = await office.get("/dashboard/overview", headers={"HX-Request": "true"})

        assert response.headers["hx-push-url"] == "/dashboard"

    async def test_poll_does_not_push_url(self, office: AsyncClient):
        """Триггер poll'а — сам контейнер #overview: адресную строку не трогаем."""
        response = await office.get(
            "/dashboard/overview",
            headers={"HX-Request": "true", "HX-Trigger": "overview"},
        )

        assert response.status_code == 200
        assert "hx-push-url" not in response.headers

    async def test_plain_request_redirected_to_page(self, office: AsyncClient):
        response = await office.get("/dashboard/overview", params={"q": "ЖК"})

        assert response.status_code == 307
        assert response.headers["location"] == "/dashboard?q=%D0%96%D0%9A"

    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/dashboard/overview", headers={"HX-Request": "true"})

        assert response.status_code == 401
        assert response.headers["hx-redirect"] == "/dashboard/login"


class TestEmptyStates:
    async def test_no_sites_at_all(self, office: AsyncClient):
        response = await office.get("/dashboard", params={"status": "all"})

        assert "Объектов пока нет" in response.text

    async def test_search_found_nothing(self, office: AsyncClient, make_site: SiteFactory):
        await make_site(name="ЖК Северный")

        response = await office.get("/dashboard", params={"q": "абракадабра"})

        assert "Ничего не найдено" in response.text

    async def test_status_without_sites_offers_all(
        self, office: AsyncClient, make_site: SiteFactory
    ):
        await make_site(name="ЖК Северный")

        response = await office.get("/dashboard", params={"status": "completed"})

        assert "Нет объектов с этим статусом" in response.text
        assert "/dashboard?status=all" in response.text


class TestDeepLink:
    async def test_filter_state_restored_in_form(self, office: AsyncClient, make_site: SiteFactory):
        """F5 и «назад» работают: состояние фильтра живёт в query-параметрах."""
        await make_site(name="Склад Южный", status=SiteStatus.COMPLETED)

        response = await office.get("/dashboard", params={"status": "completed", "q": "склад"})

        assert 'id="status-completed" checked' in response.text
        assert 'value="склад"' in response.text
        assert "Склад Южный" in response.text
