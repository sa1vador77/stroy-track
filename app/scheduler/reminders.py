"""Рассылка напоминаний прорабам, не сдавшим отчёт за сегодня."""

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import company_today
from app.models import (
    ConstructionSite,
    DailyReport,
    SiteStatus,
    User,
    UserRole,
    site_assignments,
)

log = structlog.get_logger()


async def send_report_reminders(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Одно сообщение на прораба со списком его объектов без отчёта за сегодня."""
    today = company_today()
    async with session_factory() as session:
        # роль перепроверяется, как в auth-middleware бота: не полагаемся
        # на инвариант API «на объект назначают только прорабов»
        rows = (
            await session.execute(
                select(User, ConstructionSite)
                .join(site_assignments, site_assignments.c.user_id == User.id)
                .join(ConstructionSite, ConstructionSite.id == site_assignments.c.site_id)
                .where(
                    User.role == UserRole.FOREMAN,
                    User.is_active,
                    ConstructionSite.status == SiteStatus.ACTIVE,
                    ~exists().where(
                        DailyReport.site_id == ConstructionSite.id,
                        DailyReport.foreman_id == User.id,
                        DailyReport.report_date == today,
                    ),
                )
                .order_by(User.id, ConstructionSite.id)
            )
        ).all()

    pending: dict[User, list[ConstructionSite]] = {}
    without_telegram: set[int] = set()
    for foreman, site in rows:
        if foreman.telegram_id is None:
            # офис ещё не вписал telegram_id — напомнить некуда
            without_telegram.add(foreman.id)
            continue
        pending.setdefault(foreman, []).append(site)

    sent = failed = 0
    for foreman, sites in pending.items():
        site_lines = "\n".join(f"— {site.name}" for site in sites)
        # формулировка не зависит от числа объектов — «по объектам» при одном
        # пункте списка резало бы глаз
        text = f"Напоминание: вы ещё не сдали отчёт за сегодня:\n{site_lines}\nСдать отчёт: /report"
        try:
            await bot.send_message(foreman.telegram_id, text)
        except TelegramAPIError:
            # заблокировал бота или битый telegram_id — остальные получат своё
            log.warning(
                "reminder_send_failed",
                foreman_id=foreman.id,
                telegram_id=foreman.telegram_id,
                exc_info=True,
            )
            failed += 1
            continue
        sent += 1
    log.info(
        "reminders_sent",
        report_date=today.isoformat(),
        foremen_notified=sent,
        send_failures=failed,
        without_telegram=len(without_telegram),
    )
