"""Сборка планировщика: cron-задача напоминаний по времени из настроек."""

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.scheduler.reminders import send_report_reminders


def create_scheduler(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIOScheduler:
    """Фабрика по образцу create_dispatcher: тесты собирают планировщик без запуска."""
    settings = get_settings()
    reminder_at = settings.reminder_time_parsed
    # таймзона нужна и самому планировщику: иначе next-run считался бы через
    # tzlocal, а в slim-контейнере локальная зона не настроена
    scheduler = AsyncIOScheduler(timezone=settings.company_tzinfo)
    scheduler.add_job(
        send_report_reminders,
        CronTrigger(
            hour=reminder_at.hour, minute=reminder_at.minute, timezone=settings.company_tzinfo
        ),
        args=(bot, session_factory),
        id="report_reminders",
        # дефолтный misfire_grace_time — 1 секунда: секундная заминка event loop
        # молча роняла бы суточный крон. Час прощает заминки живого процесса;
        # рестарт grace не спасает — MemoryJobStore при старте берёт следующий
        # будущий запуск, день простоя теряется (осознанный at-most-once)
        misfire_grace_time=3600,
        coalesce=True,
    )
    return scheduler
