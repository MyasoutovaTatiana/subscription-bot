"""Subscription domain service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BillingType, DEFAULT_REMINDER_OFFSETS, SplitMode
from app.models.subscription import Subscription
from app.repositories.subscriptions import SubscriptionRepository
from app.utils.money import MoneyError, parse_amount


@dataclass(slots=True)
class CreateSubscriptionDTO:
    user_id: int
    name: str
    category: str
    amount: Decimal
    currency: str
    billing_type: str
    billing_interval: int | None
    billing_day: int | None
    next_charge_date: date | None
    payment_method_id: int | None
    reminder_offsets: list[int]
    reminder_time: str
    notes: str | None = None
    include_owner_in_split: bool = True
    split_mode: str | None = None
    friend_ids: list[int] | None = None


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SubscriptionRepository(session)
        self._session = session

    async def create(self, dto: CreateSubscriptionDTO) -> Subscription:
        if dto.amount <= 0:
            raise MoneyError("Сумма должна быть больше нуля")

        billing_type = BillingType(dto.billing_type)
        if billing_type == BillingType.MONTHLY and dto.billing_day is None and dto.next_charge_date:
            billing_day = dto.next_charge_date.day
        else:
            billing_day = dto.billing_day

        if billing_type in {BillingType.EVERY_N_DAYS, BillingType.CUSTOM}:
            if not dto.billing_interval or dto.billing_interval < 1:
                raise ValueError("Укажи число дней от 1 и больше")

        sub = await self._repo.create(
            user_id=dto.user_id,
            name=dto.name.strip(),
            category=dto.category,
            amount=dto.amount,
            currency=dto.currency.upper(),
            billing_type=billing_type.value,
            billing_interval=dto.billing_interval,
            billing_day=billing_day,
            next_charge_date=dto.next_charge_date,
            payment_method_id=dto.payment_method_id,
            reminder_offsets=dto.reminder_offsets or list(DEFAULT_REMINDER_OFFSETS),
            reminder_time=dto.reminder_time,
            notes=dto.notes,
            include_owner_in_split=dto.include_owner_in_split,
            split_mode=dto.split_mode,
            is_active=True,
        )

        for friend_id in dto.friend_ids or []:
            await self._repo.add_participant(subscription_id=sub.id, friend_id=friend_id)

        # reload with relationships
        loaded = await self._repo.get_for_user(sub.id, dto.user_id)
        assert loaded is not None
        return loaded

    async def list_active(self, user_id: int) -> list[Subscription]:
        return await self._repo.list_active(user_id)

    async def get(self, subscription_id: int, user_id: int) -> Subscription | None:
        return await self._repo.get_for_user(subscription_id, user_id)

    async def deactivate(self, subscription: Subscription) -> Subscription:
        subscription.is_active = False
        return await self._repo.save(subscription)

    async def activate(self, subscription: Subscription) -> Subscription:
        subscription.is_active = True
        return await self._repo.save(subscription)

    async def delete(self, subscription: Subscription) -> None:
        await self._repo.delete(subscription)

    async def update_fields(self, subscription: Subscription, **fields) -> Subscription:
        for key, value in fields.items():
            if value is not None or key in fields:
                setattr(subscription, key, value)
        return await self._repo.save(subscription)


def validate_amount_text(raw: str) -> Decimal:
    return parse_amount(raw)
