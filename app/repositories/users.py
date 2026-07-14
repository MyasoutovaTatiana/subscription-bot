"""User repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DEFAULT_REMINDER_OFFSETS
from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
        timezone: str = "Europe/Moscow",
        default_reminder_time: str = "10:00",
    ) -> User:
        user = User(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            username=username,
            first_name=first_name,
            timezone=timezone,
            default_reminder_time=default_reminder_time,
            default_reminder_offsets=list(DEFAULT_REMINDER_OFFSETS),
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_profile(
        self,
        user: User,
        *,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        user.telegram_chat_id = telegram_chat_id
        user.username = username
        user.first_name = first_name
        await self._session.flush()
        return user
