"""Reminder delivery repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReminderStatus
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription


class ReminderDataUnavailableError(LookupError):
    """Reminder or parent subscription is not owned by the current user."""


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_unique_key(self, unique_key: str) -> ReminderDelivery | None:
        result = await self._session.execute(
            select(ReminderDelivery).where(ReminderDelivery.unique_key == unique_key)
        )
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        reminder_id: int,
        user_id: int,
    ) -> ReminderDelivery | None:
        with self._session.no_autoflush:
            result = await self._session.execute(
                select(ReminderDelivery)
                .where(
                    ReminderDelivery.id == reminder_id,
                    ReminderDelivery.user_id == user_id,
                )
                .execution_options(populate_existing=True)
            )
        return result.scalar_one_or_none()

    async def create_pending(
        self,
        *,
        user_id: int,
        subscription_id: int,
        charge_date,
        reminder_offset: int,
        scheduled_at: datetime,
        unique_key: str,
    ) -> ReminderDelivery | None:
        subscription = await self._session.scalar(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.user_id == user_id,
            )
        )
        if subscription is None:
            raise ReminderDataUnavailableError()
        expected_key = ReminderDelivery.build_unique_key(
            subscription_id,
            charge_date,
            reminder_offset,
        )
        if unique_key != expected_key:
            raise ReminderDataUnavailableError()
        existing = await self.get_by_unique_key(unique_key)
        if existing:
            return None
        row = ReminderDelivery(
            user_id=user_id,
            subscription_id=subscription_id,
            charge_date=charge_date,
            reminder_offset=reminder_offset,
            scheduled_at=scheduled_at,
            status=ReminderStatus.PENDING.value,
            unique_key=unique_key,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_sent(
        self,
        row: ReminderDelivery,
        sent_at: datetime,
        *,
        user_id: int,
    ) -> None:
        owned = await self._validated_reminder(row, user_id)
        owned.status = ReminderStatus.SENT.value
        owned.sent_at = sent_at
        await self._session.flush()

    async def mark_failed(
        self,
        row: ReminderDelivery,
        error: str,
        *,
        user_id: int,
    ) -> None:
        owned = await self._validated_reminder(row, user_id)
        owned.status = ReminderStatus.FAILED.value
        owned.error_message = error[:2000]
        await self._session.flush()

    async def list_due(self, now: datetime) -> list[ReminderDelivery]:
        result = await self._session.execute(
            select(ReminderDelivery).where(
                ReminderDelivery.status == ReminderStatus.PENDING.value,
                ReminderDelivery.scheduled_at <= now,
            )
        )
        return list(result.scalars().all())

    async def _validated_reminder(
        self,
        row: ReminderDelivery,
        user_id: int,
    ) -> ReminderDelivery:
        if row.user_id != user_id:
            raise ReminderDataUnavailableError()
        owned = await self.get_for_user(row.id, user_id)
        if owned is None:
            raise ReminderDataUnavailableError()
        return owned
