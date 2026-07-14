"""Reminder delivery repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ReminderStatus
from app.models.reminder_delivery import ReminderDelivery


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_unique_key(self, unique_key: str) -> ReminderDelivery | None:
        result = await self._session.execute(
            select(ReminderDelivery).where(ReminderDelivery.unique_key == unique_key)
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

    async def mark_sent(self, row: ReminderDelivery, sent_at: datetime) -> None:
        row.status = ReminderStatus.SENT.value
        row.sent_at = sent_at
        await self._session.flush()

    async def mark_failed(self, row: ReminderDelivery, error: str) -> None:
        row.status = ReminderStatus.FAILED.value
        row.error_message = error[:2000]
        await self._session.flush()

    async def list_due(self, now: datetime) -> list[ReminderDelivery]:
        result = await self._session.execute(
            select(ReminderDelivery).where(
                ReminderDelivery.status == ReminderStatus.PENDING.value,
                ReminderDelivery.scheduled_at <= now,
            )
        )
        return list(result.scalars().all())
