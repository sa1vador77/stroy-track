"""Тесты рассылки напоминаний о несданных отчётах."""

from datetime import UTC, datetime, timedelta

import pytest
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.core.clock import company_today
from app.core.config import get_settings
from app.models import SiteStatus, User, UserRole
from app.scheduler.reminders import send_report_reminders
from tests.conftest import (
    FOREMAN_TG_ID,
    ReportFactory,
    SiteFactory,
    UserFactory,
)
from tests.fake_telegram import RecordingSession


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(telegram_id=FOREMAN_TG_ID)


class TestWhoIsReminded:
    async def test_foreman_without_report_reminded(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
    ):
        await make_site(name="ЖК Северный", foremen=[foreman])

        await send_report_reminders(bot, db_session_factory)

        [message] = tg.sent_messages
        assert message.chat_id == FOREMAN_TG_ID
        assert "ЖК Северный" in message.text
        assert "/report" in message.text

    async def test_submitted_today_not_reminded(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        site = await make_site(foremen=[foreman])
        await make_report(site, foreman, report_date=company_today())

        await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []

    async def test_partial_reports_list_only_missing_sites(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        submitted = await make_site(name="ЖК Сданный", foremen=[foreman])
        await make_site(name="ЖК Забытый", foremen=[foreman])
        await make_report(submitted, foreman, report_date=company_today())

        await send_report_reminders(bot, db_session_factory)

        [message] = tg.sent_messages
        assert "ЖК Забытый" in message.text
        assert "ЖК Сданный" not in message.text

    async def test_yesterday_report_does_not_count(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        site = await make_site(foremen=[foreman])
        await make_report(site, foreman, report_date=company_today() - timedelta(days=1))

        await send_report_reminders(bot, db_session_factory)

        assert len(tg.sent_messages) == 1

    async def test_all_missing_sites_in_one_message_ordered(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
    ):
        first = await make_site(name="ЖК Первый", foremen=[foreman])
        second = await make_site(name="ЖК Второй", foremen=[foreman])

        await send_report_reminders(bot, db_session_factory)

        [message] = tg.sent_messages
        assert message.text.count("— ") == 2
        # порядок стабилен: по id объекта
        assert message.text.index(first.name) < message.text.index(second.name)

    async def test_each_foreman_gets_own_sites(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
    ):
        second = await make_user(telegram_id=200_500)
        await make_site(name="ЖК Первого", foremen=[foreman])
        await make_site(name="ЖК Второго", foremen=[second])

        await send_report_reminders(bot, db_session_factory)

        texts = {m.chat_id: m.text for m in tg.sent_messages}
        assert "ЖК Первого" in texts[FOREMAN_TG_ID]
        assert "ЖК Второго" not in texts[FOREMAN_TG_ID]
        assert "ЖК Второго" in texts[200_500]
        assert "ЖК Первого" not in texts[200_500]

    async def test_two_foremen_on_one_site(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
        make_report: ReportFactory,
    ):
        second = await make_user(telegram_id=200_500)
        site = await make_site(foremen=[foreman, second])
        # отчёт другого прораба по тому же объекту не закрывает мой долг:
        # уникальность отчёта — по паре (объект, прораб)
        await make_report(site, foreman, report_date=company_today())

        await send_report_reminders(bot, db_session_factory)

        [message] = tg.sent_messages
        assert message.chat_id == 200_500

    async def test_inactive_foreman_skipped(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        db_session: AsyncSession,
    ):
        await make_site(foremen=[foreman])
        foreman.is_active = False
        await db_session.commit()

        await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []

    async def test_non_foreman_role_skipped(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        make_user: UserFactory,
        make_site: SiteFactory,
    ):
        # API не назначает менеджеров на объекты, но запрос это перепроверяет —
        # та же оборона, что в auth-middleware бота
        manager = await make_user(UserRole.MANAGER, telegram_id=300_500)
        await make_site(foremen=[manager])

        await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []

    async def test_foreman_without_telegram_id_counted_in_log(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        make_user: UserFactory,
        make_site: SiteFactory,
    ):
        silent = await make_user(telegram_id=None)
        await make_site(foremen=[silent])

        with capture_logs() as logs:
            await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []
        [summary] = [entry for entry in logs if entry["event"] == "reminders_sent"]
        assert summary["without_telegram"] == 1

    @pytest.mark.parametrize("status", [SiteStatus.SUSPENDED, SiteStatus.COMPLETED])
    async def test_not_active_site_skipped(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        status: SiteStatus,
    ):
        await make_site(foremen=[foreman], status=status)

        await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []


class TestDelivery:
    async def test_send_failure_does_not_block_others(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_user: UserFactory,
        make_site: SiteFactory,
    ):
        blocked = await make_user(telegram_id=400_500)
        silent = await make_user(telegram_id=None)
        await make_site(foremen=[blocked])
        await make_site(foremen=[foreman])
        await make_site(foremen=[silent])
        tg.fail_chat_ids.add(400_500)

        with capture_logs() as logs:
            await send_report_reminders(bot, db_session_factory)

        # заблокировавший бота не остановил рассылку остальным
        delivered = [m for m in tg.sent_messages if m.chat_id == FOREMAN_TG_ID]
        assert len(delivered) == 1
        # все три счётчика в одном прогоне: успех, сбой, некому слать
        [summary] = [entry for entry in logs if entry["event"] == "reminders_sent"]
        assert summary["foremen_notified"] == 1
        assert summary["send_failures"] == 1
        assert summary["without_telegram"] == 1
        assert any(entry["event"] == "reminder_send_failed" for entry in logs)

    async def test_report_dated_in_company_tz_suppresses_reminder(
        self,
        bot: Bot,
        tg: RecordingSession,
        db_session_factory: async_sessionmaker[AsyncSession],
        foreman: User,
        make_site: SiteFactory,
        make_report: ReportFactory,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # часы замораживаются: три независимых взгляда на «сейчас» могли бы
        # разъехаться на границе суток UTC и дать плавающий тест
        frozen = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        monkeypatch.setattr("app.core.clock.datetime", _FrozenDatetime)
        # UTC+14: в полдень UTC на Киритимати уже завтра — даты гарантированно
        # разные, а запрос обязан сравнивать с «сегодня» компании, не с БД
        monkeypatch.setattr(get_settings(), "company_tz", "Pacific/Kiritimati")
        assert company_today() != frozen.date()

        site = await make_site(foremen=[foreman])
        await make_report(site, foreman, report_date=company_today())

        await send_report_reminders(bot, db_session_factory)

        assert tg.sent_messages == []
