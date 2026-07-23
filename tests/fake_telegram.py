"""Фейковая сторона Telegram: сессия-перехватчик исходящих вызовов и билдер апдейтов."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from itertools import count
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, GetFile, SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, File, Message, PhotoSize, Update
from aiogram.types import User as TgUser

# то, что «скачивается» из Telegram вместо настоящего JPEG
FAKE_JPEG = b"\xff\xd8fake-jpeg"


class RecordingSession(BaseSession):
    """Ничего не отправляет в сеть: запоминает вызовы API и отдаёт минимальные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.downloaded_paths: list[str] = []
        # chat_id, для которых отправка «падает»: тесты сбоя доставки
        self.fail_chat_ids: set[int] = set()

    @property
    def sent_messages(self) -> list[SendMessage]:
        return [m for m in self.requests if isinstance(m, SendMessage)]

    @property
    def callback_answers(self) -> list[AnswerCallbackQuery]:
        return [m for m in self.requests if isinstance(m, AnswerCallbackQuery)]

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            if method.chat_id in self.fail_chat_ids:
                raise TelegramForbiddenError(
                    method=method, message="Forbidden: bot was blocked by the user"
                )
            return Message(
                message_id=len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, GetFile):
            return File(
                file_id=method.file_id,
                file_unique_id=f"{method.file_id}-unique",
                file_path=f"photos/{method.file_id}.jpg",
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
        self.downloaded_paths.append(url)
        yield FAKE_JPEG


_update_ids = count(1)


def non_text_message_update(tg_user_id: int) -> Update:
    """Сообщение без текста (фото, стикер): message.text is None."""
    update_id = next(_update_ids)
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=tg_user_id, type="private"),
            from_user=TgUser(id=tg_user_id, is_bot=False, first_name="Прораб"),
        ),
    )


def callback_update(tg_user_id: int, data: str) -> Update:
    """Нажатие inline-кнопки; message — то сообщение бота, под которым была кнопка."""
    update_id = next(_update_ids)
    chat = Chat(id=tg_user_id, type="private")
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=TgUser(id=tg_user_id, is_bot=False, first_name="Прораб"),
            chat_instance="test",
            message=Message(message_id=update_id, date=datetime.now(UTC), chat=chat),
            data=data,
        ),
    )


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


def photo_message_update(tg_user_id: int, file_id: str = "photo-1") -> Update:
    """Фото из личного чата; message.photo — размерные варианты одного снимка."""
    update_id = next(_update_ids)
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=tg_user_id, type="private"),
            from_user=TgUser(id=tg_user_id, is_bot=False, first_name="Прораб"),
            photo=[
                PhotoSize(
                    file_id=f"{file_id}-thumb",
                    file_unique_id=f"{file_id}-thumb-unique",
                    width=90,
                    height=68,
                ),
                PhotoSize(
                    file_id=file_id,
                    file_unique_id=f"{file_id}-unique",
                    width=1280,
                    height=960,
                ),
            ],
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
