"""Security regression tests for remaining user-owned entities."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.models import Base
from app.models.enums import (
    BillingType,
    ReminderStatus,
    SubscriptionCategory,
    TransactionType,
)
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription
from app.models.transaction import TransactionSplit
from app.models.user import User
from app.repositories.reminders import (
    ReminderDataUnavailableError,
    ReminderRepository,
)
from app.repositories.transactions import TransactionRepository
from app.repositories.users import UserDataUnavailableError, UserRepository
from app.services.users import UserService


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'remaining-ownership.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_id: int) -> User:
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_id,
        telegram_chat_id=telegram_id,
        username=f"user{telegram_id}",
        first_name=f"User {telegram_id}",
    )
    return user


async def _subscription(session: AsyncSession, user_id: int) -> Subscription:
    subscription = Subscription(
        user_id=user_id,
        name="Owner subscription",
        category=SubscriptionCategory.AI_WORK.value,
        amount=Decimal("20"),
        currency="USD",
        billing_type=BillingType.MONTHLY.value,
        next_charge_date=date(2026, 8, 1),
        reminder_offsets=[1, 0],
        reminder_time="10:00",
    )
    session.add(subscription)
    await session.flush()
    return subscription


@pytest.mark.asyncio
async def test_foreign_user_profile_update_is_rejected(session: AsyncSession) -> None:
    owner = await _user(session, 101)
    attacker = await _user(session, 202)
    repo = UserRepository(session)

    with pytest.raises(UserDataUnavailableError):
        await repo.update_profile(
            owner,
            user_id=attacker.id,
            telegram_chat_id=999,
            username="stolen",
            first_name="Stolen",
        )

    unchanged = await repo.get_by_id(owner.id)
    assert unchanged is not None
    assert unchanged.telegram_chat_id == 101
    assert unchanged.username == "user101"


@pytest.mark.asyncio
async def test_forged_user_object_does_not_change_victim_profile(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 303)
    attacker = await _user(session, 404)
    forged = User(
        id=owner.id,
        telegram_user_id=attacker.telegram_user_id,
        telegram_chat_id=attacker.telegram_chat_id,
    )

    with pytest.raises(UserDataUnavailableError):
        await UserRepository(session).update_profile(
            forged,
            user_id=attacker.id,
            telegram_chat_id=999,
            username="stolen",
            first_name="Stolen",
        )

    unchanged = await UserRepository(session).get_by_id(owner.id)
    assert unchanged is not None
    assert unchanged.username == "user303"


@pytest.mark.asyncio
async def test_foreign_user_wipe_is_rejected(session: AsyncSession) -> None:
    owner = await _user(session, 505)
    attacker = await _user(session, 606)

    with pytest.raises(UserDataUnavailableError):
        await UserService(session).wipe_user(owner, user_id=attacker.id)

    assert await UserRepository(session).get_by_id(owner.id) is not None
    assert await UserRepository(session).get_by_id(attacker.id) is not None


@pytest.mark.asyncio
async def test_foreign_subscription_cannot_create_reminder(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 707)
    attacker = await _user(session, 808)
    subscription = await _subscription(session, owner.id)
    charge_date = date(2026, 8, 1)

    with pytest.raises(ReminderDataUnavailableError):
        await ReminderRepository(session).create_pending(
            user_id=attacker.id,
            subscription_id=subscription.id,
            charge_date=charge_date,
            reminder_offset=1,
            scheduled_at=datetime(2026, 7, 31, 10, tzinfo=timezone.utc),
            unique_key=ReminderDelivery.build_unique_key(
                subscription.id,
                charge_date,
                1,
            ),
        )


@pytest.mark.asyncio
async def test_forged_reminder_cannot_be_marked_sent(session: AsyncSession) -> None:
    owner = await _user(session, 909)
    attacker = await _user(session, 1001)
    subscription = await _subscription(session, owner.id)
    repo = ReminderRepository(session)
    charge_date = date(2026, 8, 1)
    reminder = await repo.create_pending(
        user_id=owner.id,
        subscription_id=subscription.id,
        charge_date=charge_date,
        reminder_offset=1,
        scheduled_at=datetime(2026, 7, 31, 10, tzinfo=timezone.utc),
        unique_key=ReminderDelivery.build_unique_key(subscription.id, charge_date, 1),
    )
    assert reminder is not None
    forged = ReminderDelivery(
        id=reminder.id,
        user_id=attacker.id,
        subscription_id=subscription.id,
        charge_date=charge_date,
        reminder_offset=1,
        scheduled_at=reminder.scheduled_at,
        unique_key=reminder.unique_key,
    )

    with pytest.raises(ReminderDataUnavailableError):
        await repo.mark_sent(forged, datetime.now(timezone.utc), user_id=attacker.id)

    unchanged = await repo.get_for_user(reminder.id, owner.id)
    assert unchanged is not None
    assert unchanged.status == ReminderStatus.PENDING.value


@pytest.mark.asyncio
async def test_owner_can_update_reminder_status(session: AsyncSession) -> None:
    owner = await _user(session, 1102)
    subscription = await _subscription(session, owner.id)
    repo = ReminderRepository(session)
    charge_date = date(2026, 8, 1)
    reminder = await repo.create_pending(
        user_id=owner.id,
        subscription_id=subscription.id,
        charge_date=charge_date,
        reminder_offset=1,
        scheduled_at=datetime(2026, 7, 31, 10, tzinfo=timezone.utc),
        unique_key=ReminderDelivery.build_unique_key(subscription.id, charge_date, 1),
    )
    assert reminder is not None

    await repo.mark_failed(reminder, "temporary error", user_id=owner.id)

    changed = await repo.get_for_user(reminder.id, owner.id)
    assert changed is not None
    assert changed.status == ReminderStatus.FAILED.value
    assert changed.error_message == "temporary error"


@pytest.mark.asyncio
async def test_split_is_only_loaded_through_owned_transaction(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1203)
    attacker = await _user(session, 1304)
    repo = TransactionRepository(session)
    transaction = await repo.create(
        user_id=owner.id,
        transaction_type=TransactionType.ONE_TIME.value,
        name="Owner payment",
        original_amount=Decimal("1000"),
        original_currency="RUB",
        estimated_rub_amount=Decimal("1000"),
        is_rate_estimated=False,
        transaction_date=date(2026, 7, 22),
    )
    split = await repo.add_split(
        transaction_id=transaction.id,
        friend_id=None,
        is_owner=True,
        amount_rub=Decimal("1000"),
    )

    assert await repo.get_for_user(transaction.id, attacker.id) is None
    owned = await repo.get_for_user(transaction.id, owner.id)
    assert owned is not None
    assert [row.id for row in owned.splits] == [split.id]
    assert await session.get(TransactionSplit, split.id) is not None
