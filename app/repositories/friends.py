"""Friend repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.friend import Friend


FRIENDS_UNAVAILABLE_MESSAGE = (
    "Список друзей изменился или недоступен. Выберите друзей ещё раз."
)


class FriendsUnavailableError(LookupError):
    """Requested friends are not all available to the current user."""

    def __init__(self) -> None:
        super().__init__(FRIENDS_UNAVAILABLE_MESSAGE)


class FriendRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: int) -> list[Friend]:
        result = await self._session.execute(
            select(Friend).where(Friend.user_id == user_id).order_by(Friend.name)
        )
        return list(result.scalars().all())

    async def get_for_user(self, friend_id: int, user_id: int) -> Friend | None:
        result = await self._session.execute(
            select(Friend).where(Friend.id == friend_id, Friend.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_ids_for_user(
        self,
        friend_ids: set[int],
        user_id: int,
    ) -> list[Friend]:
        if not friend_ids:
            return []
        result = await self._session.execute(
            select(Friend).where(
                Friend.id.in_(friend_ids),
                Friend.user_id == user_id,
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: int,
        name: str,
        telegram_username: str | None = None,
        notes: str | None = None,
    ) -> Friend:
        friend = Friend(
            user_id=user_id,
            name=name.strip(),
            telegram_username=telegram_username,
            notes=notes,
        )
        self._session.add(friend)
        await self._session.flush()
        return friend

    async def delete(self, friend: Friend) -> None:
        await self._session.delete(friend)
        await self._session.flush()
