"""Команды бота; пользователь в хендлерах уже проверен auth-middleware."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConstructionSite, User, site_assignments


def create_router() -> Router:
    """Роутер собирается фабрикой: Router нельзя включить в два диспетчера,
    а тесты создают диспетчер на каждый тест."""
    router = Router()
    router.message.register(cmd_start, CommandStart())
    return router


async def cmd_start(message: Message, session: AsyncSession, foreman: User) -> None:
    """Приветствие и список объектов прораба — сразу видно, что бот его узнал."""
    sites = (
        await session.scalars(
            select(ConstructionSite.name)
            .join(site_assignments)
            .where(site_assignments.c.user_id == foreman.id)
            .order_by(ConstructionSite.id)
        )
    ).all()
    if sites:
        site_lines = "\n".join(f"— {name}" for name in sites)
        text = f"Здравствуйте, {foreman.full_name}!\nВаши объекты:\n{site_lines}"
    else:
        text = f"Здравствуйте, {foreman.full_name}!\nВам пока не назначен ни один объект."
    await message.answer(text)
