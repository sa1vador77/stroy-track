"""Точка входа процесса бота: python -m app.bot"""

import asyncio
import sys

from aiogram import Bot

from app.bot.dispatcher import create_dispatcher
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        sys.exit("BOT_TOKEN не задан — получите токен у @BotFather и добавьте в .env")
    configure_logging(json_logs=settings.log_json)
    bot = Bot(token=settings.bot_token)
    try:
        # long polling вместо webhook: не требует публичного URL и TLS,
        # для одной реплики бота этого достаточно
        await create_dispatcher().start_polling(bot)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
