"""Точка входа процесса напоминаний: python -m app.scheduler"""

import asyncio
import signal
import sys

from aiogram import Bot

from app.core import db
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scheduler.setup import create_scheduler


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        sys.exit("BOT_TOKEN не задан в .env.bot — напоминания шлёт бот")
    configure_logging(json_logs=settings.log_json)
    bot = Bot(token=settings.bot_token)
    scheduler = create_scheduler(bot, db.session_factory)
    scheduler.start()
    # start() не блокирует: без ожидания процесс вышел бы, не стрельнув ни разу.
    # SIGTERM (docker stop) по умолчанию убивает процесс мимо finally —
    # обработчики сигналов превращают остановку в штатное завершение
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        # shutdown() лишь планирует остановку в loop; исполняют её следующие
        # await — поэтому он обязан стоять до close/dispose, не после
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await db.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
