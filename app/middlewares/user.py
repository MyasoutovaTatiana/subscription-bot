"""Ensure DB user exists for incoming updates."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.users import UserService


class UserMiddleware(BaseMiddleware):
    """Load or create application user and put it into `data['db_user']`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        if tg_user is None or session is None:
            return await handler(event, data)

        chat = data.get("event_chat")
        chat_id = chat.id if chat is not None else tg_user.id

        service = UserService(session)
        db_user, _ = await service.get_or_create_from_telegram(
            telegram_user_id=tg_user.id,
            telegram_chat_id=chat_id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            default_timezone=self._settings.timezone,
            default_reminder_time=self._settings.default_reminder_time,
        )
        data["db_user"] = db_user
        return await handler(event, data)
