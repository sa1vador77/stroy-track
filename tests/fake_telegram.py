"""Фейковая сторона Telegram: сессия-перехватчик исходящих вызовов и билдер апдейтов."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from itertools import count
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser


class RecordingSession(BaseSession):
    """Ничего не отправляет в сеть: запоминает вызовы API и отдаёт минимальные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    @property
    def sent_messages(self) -> list[SendMessage]:
        return [m for m in self.requests if isinstance(m, SendMessage)]

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        raise AssertionError(f"тест не ожидал вызова Telegram API: {type(method).__name__}")

    async def close(self) -> None:
        pass

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        raise AssertionError("тест не ожидал скачивания файла из Telegram")
        yield b""  # недостижимо: сигнатура генератора нужна, чтобы удовлетворить BaseSession


_update_ids = count(1)


def channel_post_update(channel_id: int, text: str) -> Update:
    """Пост в канале приходит без from_user — на таких апдейтах бот должен молчать."""
    update_id = next(_update_ids)
    return Update(
        update_id=update_id,
        channel_post=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=channel_id, type="channel"),
            text=text,
        ),
    )


def message_update(tg_user_id: int, text: str) -> Update:
    """Входящее текстовое сообщение из личного чата: у него id чата равен id пользователя."""
    update_id = next(_update_ids)
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=tg_user_id, type="private"),
            from_user=TgUser(id=tg_user_id, is_bot=False, first_name="Прораб"),
            text=text,
        ),
    )
