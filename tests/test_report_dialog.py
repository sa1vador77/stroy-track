"""Тесты диалога /report: шаги FSM, валидации, запись отчёта, отмена и замена."""

from datetime import datetime
from decimal import Decimal

import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from structlog.testing import capture_logs

from app.core.config import get_settings
from app.models import ConstructionSite, DailyReport, User
from tests.conftest import FOREMAN_TG_ID, MaterialFactory, ReportFactory, SiteFactory, UserFactory
from tests.fake_telegram import (
    RecordingSession,
    callback_update,
    message_update,
    non_text_message_update,
)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(telegram_id=FOREMAN_TG_ID)


@pytest.fixture
async def site(make_site: SiteFactory, foreman: User) -> ConstructionSite:
    return await make_site(name="ЖК Северный", foremen=[foreman])


def _today_str() -> str:
    return f"{datetime.now(get_settings().company_tzinfo).date():%d.%m.%Y}"


async def _walk_to_confirmation(dp: Dispatcher, bot: Bot, site: ConstructionSite) -> None:
    """Прогоняет диалог за шаг численности: сводка, а при непустом
    справочнике материалов — их выбор."""
    await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
    await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
    await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Заливка фундамента"))
    await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "8"))


class TestReportStart:
    async def test_no_sites_message(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))

        [message] = tg.sent_messages
        assert "не назначен ни один объект" in message.text

    async def test_sites_keyboard(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        make_site: SiteFactory,
    ):
        first = await make_site(name="ЖК Северный", foremen=[foreman])
        second = await make_site(name="Школа №7", foremen=[foreman])
        await make_site(name="Чужой объект")

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))

        [message] = tg.sent_messages
        buttons = [b for row in message.reply_markup.inline_keyboard for b in row]
        assert [b.text for b in buttons] == ["ЖК Северный", "Школа №7", "Отмена"]
        assert buttons[0].callback_data == f"report_site:{first.id}"
        assert buttons[1].callback_data == f"report_site:{second.id}"


class TestDialogSteps:
    async def test_happy_path_saves_report(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        db_session: AsyncSession,
    ):
        await _walk_to_confirmation(dp, bot, site)

        summary = tg.sent_messages[-1]
        assert "ЖК Северный" in summary.text
        assert _today_str() in summary.text
        assert "Заливка фундамента" in summary.text
        assert "8" in summary.text

        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        assert "Отчёт принят" in tg.sent_messages[-1].text
        report = await db_session.scalar(select(DailyReport))
        assert report.site_id == site.id
        assert report.foreman_id == foreman.id
        assert report.report_date == datetime.now(get_settings().company_tzinfo).date()
        assert report.work_description == "Заливка фундамента"
        assert report.workers_count == 8

    async def test_accepted_report_is_logged(
        self,
        dp: Dispatcher,
        bot: Bot,
        foreman: User,
        site: ConstructionSite,
    ):
        await _walk_to_confirmation(dp, bot, site)

        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        [accepted] = [entry for entry in logs if entry["event"] == "report_accepted"]
        assert accepted["site_id"] == site.id
        assert accepted["foreman_id"] == foreman.id
        assert accepted["replaced"] is False
        assert accepted["materials_count"] == 0

    async def test_foreign_site_button_rejected(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_site: SiteFactory,
    ):
        foreign = await make_site(name="Чужой объект")

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        # callback_data подделан: такой кнопки в клавиатуре прораба не было
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{foreign.id}"))

        assert "Объект вам не назначен" in tg.callback_answers[-1].text
        # диалог остался на выборе объекта: текст не воспринимается как описание работ
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Заливка"))
        assert all("Сколько рабочих" not in m.text for m in tg.sent_messages)

    async def test_blank_description_reasked(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "   "))

        assert "Опишите работы текстом" in tg.sent_messages[-1].text

    async def test_non_text_description_reasked(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        # фото или стикер: message.text is None
        await dp.feed_update(bot, non_text_message_update(FOREMAN_TG_ID))

        assert "Опишите работы текстом" in tg.sent_messages[-1].text

    @pytest.mark.parametrize(
        ("bad_input", "reply"),
        [
            ("восемь", "цифрами"),
            ("8.5", "цифрами"),
            ("-1", "не может быть"),
            ("3000000000", "не может быть"),  # больше PG INTEGER
        ],
    )
    async def test_bad_workers_count_reasked(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        bad_input: str,
        reply: str,
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Заливка фундамента"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, bad_input))

        assert reply in tg.sent_messages[-1].text
        # после переспроса корректный ввод продолжает диалог
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "8"))
        assert "Проверьте отчёт" in tg.sent_messages[-1].text

    async def test_report_over_unfinished_dialog_starts_fresh(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_site: SiteFactory,
        db_session: AsyncSession,
    ):
        other = await make_site(name="Школа №7", foremen=[foreman])
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Старое описание"))

        # повторный /report отбрасывает незаконченный диалог целиком
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        assert "За какой объект отчёт?" in tg.sent_messages[-1].text

        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{other.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Новое описание"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "3"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        [report] = (await db_session.scalars(select(DailyReport))).all()
        assert report.site_id == other.id
        assert report.work_description == "Новое описание"


class TestMaterialsInDialog:
    async def test_materials_step_offered(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
    ):
        await make_material(name="Цемент М500", unit="т")
        sand = await make_material(name="Песок", unit="м3")

        await _walk_to_confirmation(dp, bot, site)

        prompt = tg.sent_messages[-1]
        assert "Какие материалы израсходовали" in prompt.text
        buttons = [b for row in prompt.reply_markup.inline_keyboard for b in row]
        assert [b.text for b in buttons] == ["Песок (м3)", "Цемент М500 (т)", "Готово", "Отмена"]
        assert buttons[0].callback_data == f"report_material:{sand.id}"

    async def test_happy_path_with_materials(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        cement = await make_material(name="Цемент М500", unit="т")
        sand = await make_material(name="Песок", unit="м3")

        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{cement.id}"))
        assert "Например: 2,5" in tg.sent_messages[-1].text

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "2,5"))
        assert "Записал: Цемент М500 — 2,5 т" in tg.sent_messages[-1].text

        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{sand.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "10"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))

        summary = tg.sent_messages[-1]
        assert "Материалы:" in summary.text
        assert "— Цемент М500: 2,5 т" in summary.text
        assert "— Песок: 10 м3" in summary.text

        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        assert "Отчёт принят" in tg.sent_messages[-1].text
        [accepted] = [entry for entry in logs if entry["event"] == "report_accepted"]
        assert accepted["materials_count"] == 2
        report = await db_session.scalar(
            select(DailyReport).options(selectinload(DailyReport.material_usages))
        )
        quantities = {u.material_id: u.quantity for u in report.material_usages}
        assert quantities == {cement.id: Decimal("2.5"), sand.id: Decimal("10")}

    async def test_done_without_materials(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        await make_material()

        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))

        assert "Материалы" not in tg.sent_messages[-1].text
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        report = await db_session.scalar(
            select(DailyReport).options(selectinload(DailyReport.material_usages))
        )
        assert report.material_usages == []

    @pytest.mark.parametrize(
        ("text", "reply"),
        [
            ("мешок", "числом"),
            ("nan", "числом"),
            ("0", "больше нуля"),
            ("-2", "больше нуля"),
            ("1,2345", "трёх знаков"),
            ("1000000000", "Слишком большое"),
        ],
    )
    async def test_bad_quantity_reasked(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        text: str,
        reply: str,
    ):
        material = await make_material(name="Цемент", unit="т")
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, text))
        assert reply in tg.sent_messages[-1].text

        # после ошибки шаг не сбит: корректное количество принимается
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "2.5"))
        assert "Записал: Цемент — 2,5 т" in tg.sent_messages[-1].text

    async def test_duplicate_material_replaced(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        cement = await make_material(name="Цемент", unit="т")

        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{cement.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{cement.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "7"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))

        summary = tg.sent_messages[-1]
        assert summary.text.count("Цемент") == 1
        assert "Цемент: 7 т" in summary.text

        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        report = await db_session.scalar(
            select(DailyReport).options(selectinload(DailyReport.material_usages))
        )
        [usage] = report.material_usages
        assert usage.quantity == Decimal("7")
        [accepted] = [entry for entry in logs if entry["event"] == "report_accepted"]
        assert accepted["materials_count"] == 1

    async def test_forged_material_callback_rejected(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
    ):
        await make_material(name="Цемент")
        await _walk_to_confirmation(dp, bot, site)

        # мусор и несуществующий id получают один и тот же отказ
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report_material:мусор"))
        assert "уже нет" in tg.callback_answers[-1].text
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report_material:999999"))
        assert "уже нет" in tg.callback_answers[-1].text

        # шаг не сбит: текст не принимается за количество
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        assert all("Записал" not in m.text for m in tg.sent_messages)

    async def test_material_deleted_during_dialog(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        cement = await make_material(name="Цемент", unit="т")

        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{cement.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))
        await db_session.delete(cement)
        await db_session.commit()

        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        assert "уже удалены — отчёт не сохранён" in tg.sent_messages[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []
        [rejected] = [entry for entry in logs if entry["event"] == "report_rejected"]
        assert rejected["reason"] == "site_or_material_deleted"

    @pytest.mark.parametrize(
        ("text", "shown"),
        [
            ("2,5000", "2,5"),  # хвостовые нули — не точность
            ("1E5", "100000"),  # экспонента канонизируется для сводки
            ("1,234", "1,234"),  # ровно три знака — граница допуска
            ("999999999,999", "999999999,999"),  # максимум Numeric(12, 3)
        ],
    )
    async def test_quantity_normalized_and_boundaries_accepted(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        text: str,
        shown: str,
    ):
        material = await make_material(name="Цемент", unit="т")
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, text))

        assert f"Записал: Цемент — {shown} т" in tg.sent_messages[-1].text

    async def test_stale_material_button_in_live_dialog(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        material = await make_material(name="Цемент", unit="т")
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))

        # кнопка материала из старого сообщения на шаге сводки: диалог жив,
        # совет «начните заново» здесь навредил бы
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))
        assert "продолжайте текущий шаг" in tg.callback_answers[-1].text

        # состояние не сбито — отчёт отправляется
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))
        assert "Отчёт принят" in tg.sent_messages[-1].text
        assert await db_session.scalar(select(DailyReport)) is not None

    async def test_restart_drops_materials(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        material = await make_material(name="Цемент", unit="т")
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))

        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:restart"))
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:materials_done"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        report = await db_session.scalar(
            select(DailyReport).options(selectinload(DailyReport.material_usages))
        )
        assert report.material_usages == []

    async def test_cancel_button_on_materials_step(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_material: MaterialFactory,
        db_session: AsyncSession,
    ):
        material = await make_material(name="Цемент", unit="т")
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_material:{material.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))

        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:cancel"))

        assert "отменена" in tg.sent_messages[-1].text
        # накопленный расход не сохранился, состояние очищено
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))
        assert "устарела" in tg.callback_answers[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []

    async def test_empty_dictionary_skips_materials_step(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
    ):
        await _walk_to_confirmation(dp, bot, site)

        assert all("Какие материалы" not in m.text for m in tg.sent_messages)
        assert "Проверьте отчёт" in tg.sent_messages[-1].text


class TestCancelAndRestart:
    async def test_cancel_mid_dialog(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        db_session: AsyncSession,
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/cancel"))

        assert "Сдача отчёта отменена" in tg.sent_messages[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []

    async def test_cancel_without_dialog(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/cancel"))

        assert "ничего не заполняется" in tg.sent_messages[-1].text

    async def test_cancel_button_at_confirmation(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        db_session: AsyncSession,
    ):
        # отмена в последний момент: FSM заполнен целиком, но запись ещё не сделана
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:cancel"))

        assert "Сдача отчёта отменена" in tg.sent_messages[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []

    async def test_stale_cancel_button(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        # «Отмена» без активного диалога — устаревшая кнопка, а не отмена
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:cancel"))

        assert tg.sent_messages == []
        assert "устарела" in tg.callback_answers[-1].text

    async def test_restart_returns_to_site_choice(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
    ):
        await _walk_to_confirmation(dp, bot, site)
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:restart"))

        assert "За какой объект отчёт?" in tg.sent_messages[-1].text

    async def test_stale_button_alert(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        # состояния нет (например, бот перезапущен) — submit некуда применить
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        [answer] = tg.callback_answers
        assert "устарела" in answer.text
        assert answer.show_alert is True


class TestReplaceAndRaces:
    async def test_duplicate_day_warns_and_replaces(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        make_report: ReportFactory,
        db_session: AsyncSession,
    ):
        old = await make_report(
            site,
            foreman,
            report_date=datetime.now(get_settings().company_tzinfo).date(),
            work_description="Старый отчёт",
        )

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))
        assert "уже есть отчёт — новый заменит его" in tg.sent_messages[-1].text

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Новый отчёт"))
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "5"))
        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        reports = (await db_session.scalars(select(DailyReport))).all()
        assert len(reports) == 1
        assert reports[0].id != old.id
        assert reports[0].work_description == "Новый отчёт"
        [accepted] = [entry for entry in logs if entry["event"] == "report_accepted"]
        assert accepted["replaced"] is True

    async def test_unassigned_during_dialog_not_saved(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        db_session: AsyncSession,
    ):
        await _walk_to_confirmation(dp, bot, site)
        site.foremen.remove(foreman)
        await db_session.commit()

        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))

        assert "больше не назначен" in tg.sent_messages[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []
        [rejected] = [entry for entry in logs if entry["event"] == "report_rejected"]
        assert rejected["reason"] == "site_unassigned"

    async def test_site_deleted_race_not_saved(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        site: ConstructionSite,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _walk_to_confirmation(dp, bot, site)

        async def _fk_violation(_self: AsyncSession) -> None:
            raise IntegrityError("INSERT INTO daily_reports ...", {}, Exception("fk"))

        # гонку «объект удалили между проверкой и commit» данными не воспроизвести —
        # роняем сам commit, как это сделала бы БД
        monkeypatch.setattr(AsyncSession, "commit", _fk_violation)
        with capture_logs() as logs:
            await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))
        monkeypatch.undo()

        assert "уже удалены — отчёт не сохранён" in tg.sent_messages[-1].text
        assert (await db_session.scalars(select(DailyReport))).all() == []
        [rejected] = [entry for entry in logs if entry["event"] == "report_rejected"]
        assert rejected["reason"] == "site_or_material_deleted"
        assert rejected["log_level"] == "warning"
        # состояние очищено: повторный сабмит — уже устаревшая кнопка
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, "report:submit"))
        assert "устарела" in tg.callback_answers[-1].text
