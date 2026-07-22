"""Idempotent charge confirmation for (subscription_id, transaction_date)."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.handlers.subscriptions import cb_charged, cb_charged_legacy
from app.models import Base
from app.models.debt import Debt
from app.models.enums import BillingType, SplitMode, SubscriptionCategory, TransactionType
from app.models.friend import Friend
from app.models.subscription import Subscription
from app.models.transaction import Transaction, TransactionSplit
from app.repositories.friends import FriendRepository
from app.repositories.transactions import TransactionRepository
from app.services.charges import (
    CHARGE_REMINDER_STALE_MESSAGE,
    ChargeDateConflictError,
    ChargeReminderStaleError,
    ChargeService,
)
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
from app.services.users import UserService
from app.utils.callback_data import SubCb, SubPeriodCb


PERIOD = date(2026, 7, 14)


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'charge-idempotency.sqlite'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
        yield db_session


async def _user(session: AsyncSession, telegram_user_id: int = 1):
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=f"user{telegram_user_id}",
        first_name=f"User {telegram_user_id}",
    )
    return user


async def _friend(session: AsyncSession, user_id: int, name: str = "Friend") -> Friend:
    return await FriendRepository(session).create(user_id=user_id, name=name)


async def _subscription(
    session: AsyncSession,
    user_id: int,
    *,
    friend_ids: list[int] | None = None,
    next_charge_date: date = PERIOD,
    name: str = "Shared service",
) -> Subscription:
    return await SubscriptionService(session).create(
        CreateSubscriptionDTO(
            user_id=user_id,
            name=name,
            category=SubscriptionCategory.AI_WORK.value,
            amount=Decimal("120"),
            currency="RUB",
            billing_type=BillingType.MONTHLY.value,
            billing_interval=None,
            billing_day=next_charge_date.day,
            next_charge_date=next_charge_date,
            payment_method_id=None,
            reminder_offsets=[1, 0],
            reminder_time="10:00",
            include_owner_in_split=True,
            split_mode=SplitMode.EQUAL.value,
            friend_ids=friend_ids or [],
        )
    )


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_first_confirm_creates_one_transaction_and_shifts_once(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    friend = await _friend(session, owner.id)
    sub = await _subscription(session, owner.id, friend_ids=[friend.id])

    result = await ChargeService(session).confirm_charged(
        sub,
        user_id=owner.id,
        period_date=PERIOD,
    )
    await session.commit()

    assert result.already_confirmed is False
    assert result.transaction.transaction_date == PERIOD
    assert result.next_charge_date == date(2026, 8, 14)
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 2
    assert await _count(session, Debt) == 1

    reloaded = await SubscriptionService(session).get(sub.id, owner.id)
    assert reloaded is not None
    assert reloaded.next_charge_date == date(2026, 8, 14)


@pytest.mark.asyncio
async def test_two_sequential_confirms_same_period_create_one_transaction(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    friend = await _friend(session, owner.id)
    sub = await _subscription(session, owner.id, friend_ids=[friend.id])

    first = await ChargeService(session).confirm_charged(
        sub,
        user_id=owner.id,
        period_date=PERIOD,
    )
    await session.commit()
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None

    second = await ChargeService(session).confirm_charged(
        sub,
        user_id=owner.id,
        period_date=PERIOD,
    )
    await session.commit()

    assert first.already_confirmed is False
    assert second.already_confirmed is True
    assert second.transaction.id == first.transaction.id
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 2
    assert await _count(session, Debt) == 1
    assert sub.next_charge_date == date(2026, 8, 14)


@pytest.mark.asyncio
async def test_replay_does_not_create_extra_splits_or_debts(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    friend = await _friend(session, owner.id)
    sub = await _subscription(session, owner.id, friend_ids=[friend.id])
    service = ChargeService(session)

    await service.confirm_charged(sub, user_id=owner.id, period_date=PERIOD)
    await session.commit()
    splits_before = await _count(session, TransactionSplit)
    debts_before = await _count(session, Debt)
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    next_before = sub.next_charge_date

    replay = await service.confirm_charged(sub, user_id=owner.id, period_date=PERIOD)
    await session.commit()

    assert replay.already_confirmed is True
    assert await _count(session, TransactionSplit) == splits_before
    assert await _count(session, Debt) == debts_before
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    assert sub.next_charge_date == next_before


@pytest.mark.asyncio
async def test_next_period_confirms_separately(session: AsyncSession) -> None:
    owner = await _user(session)
    sub = await _subscription(session, owner.id)
    service = ChargeService(session)

    first = await service.confirm_charged(sub, user_id=owner.id, period_date=PERIOD)
    await session.commit()
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    assert sub.next_charge_date == date(2026, 8, 14)

    second = await service.confirm_charged(
        sub,
        user_id=owner.id,
        period_date=date(2026, 8, 14),
    )
    await session.commit()

    assert first.already_confirmed is False
    assert second.already_confirmed is False
    assert second.transaction.id != first.transaction.id
    assert await _count(session, Transaction) == 2
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    assert sub.next_charge_date == date(2026, 9, 14)


@pytest.mark.asyncio
async def test_callback_with_past_or_future_period_rejected(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    sub = await _subscription(session, owner.id)
    service = ChargeService(session)

    with pytest.raises(ChargeReminderStaleError):
        await service.confirm_charged(
            sub,
            user_id=owner.id,
            period_date=PERIOD - timedelta(days=1),
        )
    with pytest.raises(ChargeReminderStaleError):
        await service.confirm_charged(
            sub,
            user_id=owner.id,
            period_date=PERIOD + timedelta(days=1),
        )
    assert await _count(session, Transaction) == 0
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    assert sub.next_charge_date == PERIOD


@pytest.mark.asyncio
async def test_legacy_callback_without_date_creates_nothing(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    sub = await _subscription(session, owner.id)
    before = sub.next_charge_date
    callback = _callback()

    await cb_charged_legacy(
        callback,
        SubCb(action="charged", sid=sub.id),
        session,
        owner,
    )

    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None
    assert sub.next_charge_date == before
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        CHARGE_REMINDER_STALE_MESSAGE,
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_foreign_subscription_period_callback_neutral(
    session: AsyncSession,
) -> None:
    current_user = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _subscription(session, other.id)
    callback = _callback()
    state = AsyncMock()

    await cb_charged(
        callback,
        SubPeriodCb(
            action="charged",
            sid=foreign.id,
            period=PERIOD.strftime("%Y%m%d"),
        ),
        state,
        session,
        current_user,
    )

    assert await _count(session, Transaction) == 0
    callback.answer.assert_awaited_once_with("Подписка не найдена", show_alert=True)
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_duplicate(engine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as setup:
        owner = await _user(setup)
        friend = await _friend(setup, owner.id)
        sub = await _subscription(setup, owner.id, friend_ids=[friend.id])
        await setup.commit()
        user_id = owner.id
        sub_id = sub.id

    barrier = asyncio.Barrier(2)
    results: list = []

    async def _race() -> None:
        async with factory() as session:
            sub = await SubscriptionService(session).get(sub_id, user_id)
            assert sub is not None
            await barrier.wait()
            result = await ChargeService(session).confirm_charged(
                sub,
                user_id=user_id,
                period_date=PERIOD,
            )
            await session.commit()
            results.append(result)

    await asyncio.gather(_race(), _race())

    assert len(results) == 2
    assert sum(1 for r in results if not r.already_confirmed) == 1
    assert sum(1 for r in results if r.already_confirmed) == 1
    assert results[0].transaction.id == results[1].transaction.id

    async with factory() as session:
        assert await _count(session, Transaction) == 1
        assert await _count(session, TransactionSplit) == 2
        assert await _count(session, Debt) == 1
        sub = await SubscriptionService(session).get(sub_id, user_id)
        assert sub is not None
        assert sub.next_charge_date == date(2026, 8, 14)


@pytest.mark.asyncio
async def test_update_charge_date_to_occupied_period_is_safe(
    session: AsyncSession,
) -> None:
    owner = await _user(session)
    sub = await _subscription(session, owner.id)
    service = ChargeService(session)

    first = await service.confirm_charged(sub, user_id=owner.id, period_date=PERIOD)
    await session.commit()
    sub = await SubscriptionService(session).get(sub.id, owner.id)
    assert sub is not None

    second = await service.confirm_charged(
        sub,
        user_id=owner.id,
        period_date=date(2026, 8, 14),
    )
    await session.commit()
    first_id = first.transaction.id
    second_id = second.transaction.id

    tx = await service.get_for_user(second_id, owner.id)
    assert tx is not None
    with pytest.raises(ChargeDateConflictError):
        await service.update_charge_date(tx, PERIOD, user_id=owner.id)

    # Session remains usable after conflict.
    still = await service.get_for_user(first_id, owner.id)
    assert still is not None
    assert still.transaction_date == PERIOD
    tx = await service.get_for_user(second_id, owner.id)
    assert tx is not None
    assert tx.transaction_date == date(2026, 8, 14)
    assert await _count(session, Transaction) == 2


@pytest.mark.asyncio
async def test_different_subscriptions_same_date_ok(session: AsyncSession) -> None:
    owner = await _user(session)
    first = await _subscription(session, owner.id, name="One")
    second = await _subscription(session, owner.id, name="Two")
    service = ChargeService(session)

    r1 = await service.confirm_charged(first, user_id=owner.id, period_date=PERIOD)
    r2 = await service.confirm_charged(second, user_id=owner.id, period_date=PERIOD)
    await session.commit()

    assert r1.transaction.id != r2.transaction.id
    assert await _count(session, Transaction) == 2


@pytest.mark.asyncio
async def test_null_subscription_id_allows_same_date(session: AsyncSession) -> None:
    owner = await _user(session)
    repo = TransactionRepository(session)
    for _ in range(2):
        await repo.create(
            user_id=owner.id,
            subscription_id=None,
            transaction_type=TransactionType.ONE_TIME.value,
            name="One-off",
            category=None,
            original_amount=Decimal("10"),
            original_currency="RUB",
            exchange_rate=None,
            exchange_rate_date=None,
            estimated_rub_amount=Decimal("10.00"),
            actual_rub_amount=Decimal("10.00"),
            is_rate_estimated=False,
            conversion_mode=None,
            transaction_date=PERIOD,
            payment_method_id=None,
            split_mode=None,
            include_owner_in_split=True,
        )
    await session.commit()
    assert await _count(session, Transaction) == 2


@pytest.mark.asyncio
async def test_unique_index_rejects_duplicate_insert(session: AsyncSession) -> None:
    owner = await _user(session)
    sub = await _subscription(session, owner.id)
    repo = TransactionRepository(session)
    kwargs = dict(
        user_id=owner.id,
        subscription_id=sub.id,
        transaction_type=TransactionType.SUBSCRIPTION.value,
        name=sub.name,
        category=sub.category,
        original_amount=sub.amount,
        original_currency=sub.currency,
        exchange_rate=None,
        exchange_rate_date=None,
        estimated_rub_amount=Decimal("120.00"),
        actual_rub_amount=None,
        is_rate_estimated=True,
        conversion_mode=None,
        transaction_date=PERIOD,
        payment_method_id=None,
        split_mode=None,
        include_owner_in_split=True,
    )
    await repo.create(**kwargs)
    await session.commit()
    with pytest.raises(IntegrityError):
        await repo.create(**kwargs)
    await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["split", "debt", "subscription"])
async def test_confirm_failure_rolls_back_all_charge_entities(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    owner = await _user(session)
    friend = await _friend(session, owner.id)
    sub = await _subscription(session, owner.id, friend_ids=[friend.id])
    user_id = owner.id
    sub_id = sub.id
    service = ChargeService(session)

    if failure_point == "split":
        monkeypatch.setattr(
            service._tx,
            "add_split",
            AsyncMock(side_effect=RuntimeError("forced split failure")),
        )
    elif failure_point == "debt":
        monkeypatch.setattr(
            service._debts,
            "create",
            AsyncMock(side_effect=RuntimeError("forced debt failure")),
        )
    else:
        monkeypatch.setattr(
            service._subs,
            "save",
            AsyncMock(side_effect=RuntimeError("forced subscription failure")),
        )

    with pytest.raises(RuntimeError, match="forced"):
        await service.confirm_charged(sub, user_id=user_id, period_date=PERIOD)

    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0
    reloaded = await SubscriptionService(session).get(sub_id, user_id)
    assert reloaded is not None
    assert reloaded.next_charge_date == PERIOD


@pytest.mark.asyncio
async def test_confirm_can_retry_after_rolled_back_failure(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await _user(session)
    friend = await _friend(session, owner.id)
    sub = await _subscription(session, owner.id, friend_ids=[friend.id])
    user_id = owner.id
    sub_id = sub.id
    service = ChargeService(session)
    original_create = service._debts.create
    monkeypatch.setattr(
        service._debts,
        "create",
        AsyncMock(side_effect=RuntimeError("forced debt failure")),
    )

    with pytest.raises(RuntimeError, match="forced debt failure"):
        await service.confirm_charged(sub, user_id=user_id, period_date=PERIOD)

    monkeypatch.setattr(service._debts, "create", original_create)
    sub = await SubscriptionService(session).get(sub_id, user_id)
    assert sub is not None
    result = await service.confirm_charged(sub, user_id=user_id, period_date=PERIOD)
    await session.commit()

    assert result.already_confirmed is False
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 2
    assert await _count(session, Debt) == 1
    sub = await SubscriptionService(session).get(sub_id, user_id)
    assert sub is not None
    assert sub.next_charge_date == date(2026, 8, 14)
