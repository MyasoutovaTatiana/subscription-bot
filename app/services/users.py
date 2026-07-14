"""User application service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.users import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get_or_create_from_telegram(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
        default_timezone: str = "Europe/Moscow",
        default_reminder_time: str = "10:00",
    ) -> tuple[User, bool]:
        """
        Ensure a User row exists for the Telegram account.

        Returns (user, created).
        """
        user = await self._repo.get_by_telegram_id(telegram_user_id)
        if user is None:
            user = await self._repo.create(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                username=username,
                first_name=first_name,
                timezone=default_timezone,
                default_reminder_time=default_reminder_time,
            )
            return user, True

        await self._repo.update_profile(
            user,
            telegram_chat_id=telegram_chat_id,
            username=username,
            first_name=first_name,
        )
        return user, False
