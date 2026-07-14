"""Тесты каркаса бота: аутентификация по telegram_id и команда /start."""

import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from tests.conftest import FOREMAN_TG_ID, SiteFactory, UserFactory
from tests.fake_telegram import (
    RecordingSession,
    callback_update,
    channel_post_update,
    message_update,
)


@pytest.fixture
async def foreman(make_user: UserFactory) -> User:
    return await make_user(telegram_id=FOREMAN_TG_ID)


class TestAuth:
    async def test_unknown_user_gets_id_hint(self, dp: Dispatcher, bot: Bot, tg: RecordingSession):
        await dp.feed_update(bot, message_update(999, "/start"))

        [message] = tg.sent_messages
        assert "не зарегистрированы" in message.text
        # свой ID пользователю больше взять неоткуда — его сообщает бот
        assert "999" in message.text

    async def test_update_without_sender_ignored(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession
    ):
        await dp.feed_update(bot, channel_post_update(-100_500, "/start"))

        assert tg.sent_messages == []

    async def test_manager_refused(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, make_user: UserFactory
    ):
        await make_user(UserRole.MANAGER, telegram_id=200)

        await dp.feed_update(bot, message_update(200, "/start"))

        [message] = tg.sent_messages
        assert "только действующим прорабам" in message.text

    async def test_inactive_foreman_refused(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        db_session: AsyncSession,
    ):
        foreman.is_active = False
        await db_session.commit()

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/start"))

        [message] = tg.sent_messages
        assert "только действующим прорабам" in message.text


class TestStart:
    async def test_start_lists_assigned_sites(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        make_site: SiteFactory,
    ):
        await make_site(name="ЖК Северный", foremen=[foreman])
        await make_site(name="Школа №7", foremen=[foreman])
        await make_site(name="Чужой объект")

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/start"))

        [message] = tg.sent_messages
        assert message.chat_id == FOREMAN_TG_ID
        assert foreman.full_name in message.text
        assert "ЖК Северный" in message.text
        assert "Школа №7" in message.text
        assert "Чужой объект" not in message.text

    async def test_start_without_sites(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/start"))

        [message] = tg.sent_messages
        assert "не назначен ни один объект" in message.text

    async def test_plain_text_not_answered(
        self, dp: Dispatcher, bot: Bot, tg: RecordingSession, foreman: User
    ):
        # аутентификация прошла, но хендлера для свободного текста нет — бот молчит
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "привет"))

        assert tg.sent_messages == []

    async def test_start_resets_report_dialog(
        self,
        dp: Dispatcher,
        bot: Bot,
        tg: RecordingSession,
        foreman: User,
        make_site: SiteFactory,
    ):
        site = await make_site(name="ЖК Северный", foremen=[foreman])
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/report"))
        await dp.feed_update(bot, callback_update(FOREMAN_TG_ID, f"report_site:{site.id}"))

        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "/start"))

        # диалог сброшен: текст после /start больше не воспринимается как описание работ
        await dp.feed_update(bot, message_update(FOREMAN_TG_ID, "Заливка фундамента"))
        assert all("Сколько рабочих" not in m.text for m in tg.sent_messages)
