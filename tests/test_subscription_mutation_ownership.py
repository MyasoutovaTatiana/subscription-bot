"""Security checks for owner-scoped subscription mutations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.models import Base
from app.models.enums import BillingType, SubscriptionCategory
from app.models.subscription import Subscription
from app.services.subscriptions import (
    CreateSubscriptionDTO,
    SubscriptionDataUnavailableError,
    SubscriptionService,
)
from app.services.users import UserService


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'subscription-ownership.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_id: int):
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_id,
        telegram_chat_id=telegram_id,
        username=f"user{telegram_id}",
        first_name=f"User {telegram_id}",
    )
    return user


async def _subscription(session: AsyncSession, user_id: int) -> Subscription:
    return await SubscriptionService(session).create(
        CreateSubscriptionDTO(
            user_id=user_id,
            name="Owner subscription",
            category=SubscriptionCategory.AI_WORK.value,
            amount=Decimal("20"),
            currency="USD",
            billing_type=BillingType.MONTHLY.value,
            billing_interval=None,
            billing_day=20,
            next_charge_date=date(2026, 7, 20),
            payment_method_id=None,
            reminder_offsets=[1, 0],
            reminder_time="10:00",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["deactivate", "activate", "delete", "update"])
async def test_foreign_subscription_mutation_is_rejected(
    session: AsyncSession,
    operation: str,
) -> None:
    owner = await _user(session, 101)
    attacker = await _user(session, 202)
    owner_id = owner.id
    subscription = await _subscription(session, owner.id)
    subscription_id = subscription.id
    service = SubscriptionService(session)

    with pytest.raises(SubscriptionDataUnavailableError):
        if operation == "deactivate":
            await service.deactivate(subscription, user_id=attacker.id)
        elif operation == "activate":
            await service.activate(subscription, user_id=attacker.id)
        elif operation == "delete":
            await service.delete(subscription, user_id=attacker.id)
        else:
            await service.update_fields(
                subscription,
                user_id=attacker.id,
                name="Stolen",
            )

    session.expire_all()
    unchanged = await service.get(subscription_id, owner_id)
    assert unchanged is not None
    assert unchanged.name == "Owner subscription"
    assert unchanged.is_active is True


@pytest.mark.asyncio
async def test_forged_owner_field_does_not_bypass_database_scope(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 303)
    attacker = await _user(session, 404)
    owner_id = owner.id
    subscription = await _subscription(session, owner.id)
    subscription_id = subscription.id
    forged = Subscription(
        id=subscription.id,
        user_id=attacker.id,
        name=subscription.name,
        category=subscription.category,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_type=subscription.billing_type,
        billing_interval=subscription.billing_interval,
        billing_day=subscription.billing_day,
        next_charge_date=subscription.next_charge_date,
        payment_method_id=None,
        reminder_offsets=subscription.reminder_offsets,
        reminder_time=subscription.reminder_time,
        notes=None,
        include_owner_in_split=True,
        split_mode=None,
        is_active=True,
    )

    with pytest.raises(SubscriptionDataUnavailableError):
        await SubscriptionService(session).update_fields(
            forged,
            user_id=attacker.id,
            name="Stolen",
        )

    session.expire_all()
    unchanged = await SubscriptionService(session).get(subscription_id, owner_id)
    assert unchanged is not None
    assert unchanged.name == "Owner subscription"


@pytest.mark.asyncio
async def test_owner_can_mutate_subscription(session: AsyncSession) -> None:
    owner = await _user(session, 505)
    subscription = await _subscription(session, owner.id)
    service = SubscriptionService(session)

    subscription = await service.deactivate(subscription, user_id=owner.id)
    assert subscription.is_active is False
    subscription = await service.activate(subscription, user_id=owner.id)
    assert subscription.is_active is True
    subscription = await service.update_fields(
        subscription,
        user_id=owner.id,
        name="Updated",
    )
    assert subscription.name == "Updated"

    await service.delete(subscription, user_id=owner.id)
    assert await service.get(subscription.id, owner.id) is None
