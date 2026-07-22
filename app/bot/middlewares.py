"""Middleware бота: сессия БД на апдейт и допуск только действующих прорабов."""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import User, UserRole

log = structlog.get_logger()


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждый апдейт; фабрика инжектируется —
    аналог FastAPI-зависимости get_session и её подмены в тестах."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class ForemanAuthMiddleware(BaseMiddleware):
    """Пускает к хендлерам только активных прорабов с известным telegram_id.

    Пароля у прораба нет — Telegram уже подтвердил владение аккаунтом,
    дальше достаточно найти этот telegram_id в справочнике пользователей.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            # служебные апдейты без отправителя (например, из каналов) боту не интересны
            return None
        session: AsyncSession = data["session"]
        user = await session.scalar(select(User).where(User.telegram_id == tg_user.id))
        if user is None:
            log.info("bot_access_denied", reason="unknown_telegram_id", telegram_id=tg_user.id)
            # подсказываем ID для онбординга: офис впишет его в карточку прораба
            await data["bot"].send_message(
                tg_user.id,
                "Вы не зарегистрированы. Передайте в офис ваш Telegram ID: "
                f"{tg_user.id} — и вас подключат.",
            )
            return None
        if not user.is_active or user.role != UserRole.FOREMAN:
            log.info(
                "bot_access_denied",
                reason="not_active_foreman",
                telegram_id=tg_user.id,
                user_id=user.id,
            )
            await data["bot"].send_message(tg_user.id, "Бот доступен только действующим прорабам.")
            return None
        data["foreman"] = user
        return await handler(event, data)
