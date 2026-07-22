"""Subscription repository."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.subscription import Subscription, SubscriptionParticipant


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> Subscription:
        sub = Subscription(**kwargs)
        self._session.add(sub)
        await self._session.flush()
        return sub

    async def add_participant(
        self,
        *,
        subscription_id: int,
        friend_id: int,
        share_value: Decimal | None = None,
    ) -> SubscriptionParticipant:
        row = SubscriptionParticipant(
            subscription_id=subscription_id,
            friend_id=friend_id,
            share_value=share_value,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def replace_participants(
        self,
        *,
        subscription: Subscription,
        friend_ids: list[int],
    ) -> None:
        retained_shares = {
            participant.friend_id: participant.share_value
            for participant in subscription.participants
        }
        subscription.participants.clear()
        for friend_id in friend_ids:
            subscription.participants.append(
                SubscriptionParticipant(
                    friend_id=friend_id,
                    share_value=retained_shares.get(friend_id),
                )
            )
        await self._session.flush()

    async def list_active(self, user_id: int) -> list[Subscription]:
        result = await self._session.execute(
            select(Subscription)
            .options(
                selectinload(Subscription.payment_method),
                selectinload(Subscription.participants),
            )
            .where(Subscription.user_id == user_id, Subscription.is_active.is_(True))
            .order_by(Subscription.next_charge_date.nulls_last(), Subscription.name)
        )
        return list(result.scalars().all())

    async def list_upcoming(
        self,
        user_id: int,
        *,
        until: date | None = None,
    ) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .options(selectinload(Subscription.payment_method))
            .where(
                Subscription.user_id == user_id,
                Subscription.is_active.is_(True),
                Subscription.next_charge_date.is_not(None),
            )
            .order_by(Subscription.next_charge_date, Subscription.name)
        )
        if until is not None:
            stmt = stmt.where(Subscription.next_charge_date <= until)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(self, subscription_id: int, user_id: int) -> Subscription | None:
        result = await self._session.execute(
            select(Subscription)
            .options(
                selectinload(Subscription.payment_method),
                selectinload(Subscription.participants).selectinload(SubscriptionParticipant.friend),
            )
            .where(Subscription.id == subscription_id, Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def save(self, subscription: Subscription) -> Subscription:
        await self._session.flush()
        return subscription

    async def delete(self, subscription: Subscription) -> None:
        await self._session.delete(subscription)
        await self._session.flush()
