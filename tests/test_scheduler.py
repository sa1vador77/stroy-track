"""Тесты сборки планировщика напоминаний."""

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.scheduler.reminders import send_report_reminders
from app.scheduler.setup import create_scheduler


async def test_reminder_job_registered(
    bot: Bot, db_session_factory: async_sessionmaker[AsyncSession]
):
    scheduler = create_scheduler(bot, db_session_factory)

    [job] = scheduler.get_jobs()
    assert job.func is send_report_reminders
    assert job.args == (bot, db_session_factory)
    # крон собран из reminder_time (дефолт 20:00) в поясе компании
    assert "hour='20'" in str(job.trigger)
    assert "minute='0'" in str(job.trigger)
    assert str(job.trigger.timezone) == "Europe/Moscow"
    assert str(scheduler.timezone) == "Europe/Moscow"
    # секундный дефолтный grace молча пропускал бы суточный крон
    assert job.misfire_grace_time == 3600
    assert job.coalesce is True
