"""Сборка диспетчера: middleware в нужном порядке и роутеры команд."""

from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import commands, report
from app.bot.middlewares import DbSessionMiddleware, ForemanAuthMiddleware
from app.core import db


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> Dispatcher:
    """Фабрика вместо модульного диспетчера: тесты передают свою фабрику сессий."""
    dp = Dispatcher()
    # outer-middleware на dp.update видят каждый апдейт до фильтров;
    # порядок обязателен: auth берёт сессию, открытую session-middleware
    dp.update.outer_middleware(DbSessionMiddleware(session_factory or db.session_factory))
    dp.update.outer_middleware(ForemanAuthMiddleware())
    dp.include_router(commands.create_router())
    # report — последним: в его хвосте ловушка для устаревших кнопок
    dp.include_router(report.create_router())
    return dp
