"""Security checks for confirming charges from legacy subscriptions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.handlers.subscriptions import cb_charged
from app.models import Base
from app.models.debt import Debt
from app.models.enums import BillingType, SplitMode, SubscriptionCategory
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit
from app.repositories.friends import FriendRepository
from app.repositories.payment_methods import PaymentMethodRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.services.charges import (
    CHARGE_DATA_UNAVAILABLE_MESSAGE,
    ChargeDataUnavailableError,
    ChargeService,
)
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
from app.services.users import UserService
from app.utils.callback_data import SubPeriodCb


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'charge-ownership.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
        yield db_session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_user_id: int):
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=f"user{telegram_user_id}",
        first_name=f"User {telegram_user_id}",
    )
    return user


async def _friend(session: AsyncSession, user_id: int, name: str) -> Friend:
    return await FriendRepository(session).create(user_id=user_id, name=name)


async def _payment_method(
    session: AsyncSession,
    user_id: int,
    name: str,
) -> PaymentMethod:
    return await PaymentMethodRepository(session).create(user_id=user_id, name=name)


async def _subscription(
    session: AsyncSession,
    user_id: int,
    *,
    payment_method_id: int | None = None,
    friend_ids: list[int] | None = None,
) -> Subscription:
    return await SubscriptionService(session).create(
        CreateSubscriptionDTO(
            user_id=user_id,
            name="Shared service",
            category=SubscriptionCategory.AI_WORK.value,
            amount=Decimal("120"),
            currency="RUB",
            billing_type=BillingType.MONTHLY.value,
            billing_interval=None,
            billing_day=14,
            next_charge_date=date(2026, 7, 14),
            payment_method_id=payment_method_id,
            reminder_offsets=[1, 0],
            reminder_time="10:00",
            include_owner_in_split=True,
            split_mode=SplitMode.EQUAL.value,
            friend_ids=friend_ids or [],
        )
    )


async def _reload_subscription(
    session: AsyncSession,
    subscription_id: int,
    user_id: int,
) -> Subscription:
    await session.commit()
    subscription = await SubscriptionService(session).get(subscription_id, user_id)
    assert subscription is not None
    await session.refresh(subscription, ["payment_method", "participants"])
    return subscription


async def _count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def _column_snapshot(model) -> dict[str, object]:
    return {
        column.key: getattr(model, column.key)
        for column in model.__table__.columns
    }


async def _assert_no_charge_records(session: AsyncSession) -> None:
    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0
    assert await _count(session, ReminderDelivery) == 0


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_confirm_valid_owned_links_creates_expected_charge(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    method = await _payment_method(session, owner.id, "Owner card")
    first = await _friend(session, owner.id, "First")
    second = await _friend(session, owner.id, "Second")
    subscription = await _subscription(
        session,
        owner.id,
        payment_method_id=method.id,
        friend_ids=[first.id, second.id],
    )
    participant_ids = [participant.friend_id for participant in subscription.participants]

    tx, next_date, _estimated, _actual = await ChargeService(session).confirm_charged(
        subscription,
        user_id=owner.id,
    )

    loaded_tx = await ChargeService(session).get_for_user(tx.id, owner.id)
    assert loaded_tx is not None
    assert loaded_tx.payment_method_id == method.id
    assert next_date == date(2026, 8, 14)
    assert subscription.next_charge_date == next_date
    assert subscription.amount == Decimal("120")
    assert subscription.is_active is True
    assert [participant.friend_id for participant in subscription.participants] == participant_ids
    assert len(loaded_tx.splits) == 3
    assert sorted(split.amount_rub for split in loaded_tx.splits) == [
        Decimal("40.00"),
        Decimal("40.00"),
        Decimal("40.00"),
    ]
    assert len(loaded_tx.debts) == 2
    assert {debt.friend_id for debt in loaded_tx.debts} == {first.id, second.id}
    assert {debt.amount_rub for debt in loaded_tx.debts} == {Decimal("40.00")}


@pytest.mark.asyncio
async def test_confirm_allows_none_payment_method(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    friend = await _friend(session, owner.id, "Owned friend")
    subscription = await _subscription(session, owner.id, friend_ids=[friend.id])

    tx, next_date, _estimated, _actual = await ChargeService(session).confirm_charged(
        subscription,
        user_id=owner.id,
    )

    assert tx.payment_method_id is None
    assert next_date == date(2026, 8, 14)
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 2
    assert await _count(session, Debt) == 1


@pytest.mark.asyncio
async def test_confirm_allows_empty_participants(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    method = await _payment_method(session, owner.id, "Owner card")
    subscription = await _subscription(
        session,
        owner.id,
        payment_method_id=method.id,
    )

    tx, next_date, _estimated, _actual = await ChargeService(session).confirm_charged(
        subscription,
        user_id=owner.id,
    )

    assert tx.payment_method_id == method.id
    assert next_date == date(2026, 8, 14)
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0


@pytest.mark.asyncio
async def test_confirm_allows_owned_inactive_payment_method(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    method = await _payment_method(session, owner.id, "Old card")
    subscription = await _subscription(
        session,
        owner.id,
        payment_method_id=method.id,
    )
    await PaymentMethodRepository(session).deactivate(method)

    tx, _next_date, _estimated, _actual = await ChargeService(session).confirm_charged(
        subscription,
        user_id=owner.id,
    )

    assert method.is_active is False
    assert tx.payment_method_id == method.id


@pytest.mark.asyncio
async def test_confirm_rejects_foreign_payment_method_atomically(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign_method = await _payment_method(session, other.id, "Other card")
    subscription = await _subscription(session, owner.id)
    subscription.payment_method_id = foreign_method.id
    await session.flush()
    subscription = await _reload_subscription(session, subscription.id, owner.id)
    subscription_before = _column_snapshot(subscription)
    method_before = _column_snapshot(foreign_method)

    with pytest.raises(ChargeDataUnavailableError):
        await ChargeService(session).confirm_charged(
            subscription,
            user_id=owner.id,
        )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert _column_snapshot(foreign_method) == method_before


@pytest.mark.asyncio
async def test_confirm_rejects_payment_method_deleted_after_subscription_load(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    method = await _payment_method(session, owner.id, "Deleted card")
    subscription = await _subscription(
        session,
        owner.id,
        payment_method_id=method.id,
    )
    method_id = method.id
    original_next_date = subscription.next_charge_date
    await session.commit()

    async with AsyncSession(bind=session.bind, expire_on_commit=False) as other_session:
        deleted_method = await other_session.get(PaymentMethod, method_id)
        assert deleted_method is not None
        await other_session.delete(deleted_method)
        await other_session.commit()

    assert subscription.payment_method_id == method_id
    subscription_before = _column_snapshot(subscription)
    with pytest.raises(ChargeDataUnavailableError):
        await ChargeService(session).confirm_charged(
            subscription,
            user_id=owner.id,
        )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert subscription.next_charge_date == original_next_date


@pytest.mark.asyncio
async def test_confirm_rejects_foreign_participant_atomically(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign_friend = await _friend(session, other.id, "Other friend")
    subscription = await _subscription(session, owner.id)
    await SubscriptionRepository(session).add_participant(
        subscription_id=subscription.id,
        friend_id=foreign_friend.id,
    )
    subscription = await _reload_subscription(session, subscription.id, owner.id)
    subscription_before = _column_snapshot(subscription)
    participant_ids = [participant.friend_id for participant in subscription.participants]
    friend_before = _column_snapshot(foreign_friend)

    with pytest.raises(ChargeDataUnavailableError):
        await ChargeService(session).confirm_charged(
            subscription,
            user_id=owner.id,
        )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert [participant.friend_id for participant in subscription.participants] == participant_ids
    assert _column_snapshot(foreign_friend) == friend_before


@pytest.mark.asyncio
async def test_confirm_rejects_mixed_owned_and_foreign_participants(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    owned_friend = await _friend(session, owner.id, "Owned friend")
    foreign_friend = await _friend(session, other.id, "Other friend")
    subscription = await _subscription(
        session,
        owner.id,
        friend_ids=[owned_friend.id],
    )
    await SubscriptionRepository(session).add_participant(
        subscription_id=subscription.id,
        friend_id=foreign_friend.id,
    )
    subscription = await _reload_subscription(session, subscription.id, owner.id)
    subscription_before = _column_snapshot(subscription)
    owned_friend_before = _column_snapshot(owned_friend)
    foreign_friend_before = _column_snapshot(foreign_friend)

    with pytest.raises(ChargeDataUnavailableError):
        await ChargeService(session).confirm_charged(
            subscription,
            user_id=owner.id,
        )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert _column_snapshot(owned_friend) == owned_friend_before
    assert _column_snapshot(foreign_friend) == foreign_friend_before


@pytest.mark.asyncio
async def test_confirm_rejects_duplicate_participant_atomically(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    friend = await _friend(session, owner.id, "Owned friend")
    subscription = await _subscription(
        session,
        owner.id,
        friend_ids=[friend.id],
    )
    await SubscriptionRepository(session).add_participant(
        subscription_id=subscription.id,
        friend_id=friend.id,
    )
    subscription = await _reload_subscription(session, subscription.id, owner.id)
    subscription_before = _column_snapshot(subscription)
    friend_before = _column_snapshot(friend)
    participant_ids = [participant.friend_id for participant in subscription.participants]
    assert len(participant_ids) == 2
    assert set(participant_ids) == {friend.id}

    with pytest.raises(ChargeDataUnavailableError):
        await ChargeService(session).confirm_charged(
            subscription,
            user_id=owner.id,
        )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert _column_snapshot(friend) == friend_before


@pytest.mark.asyncio
async def test_confirm_rejects_wrong_service_user(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    subscription = await _subscription(session, owner.id)
    subscription_before = _column_snapshot(subscription)

    service = ChargeService(session)
    with pytest.raises(ChargeDataUnavailableError):
        await service.confirm_charged(subscription, user_id=other.id)

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    ["update_actual_rub", "update_charge_date", "update_rate", "recalculate_debts"],
)
async def test_all_public_rebuild_paths_reject_foreign_participant_before_changes(
    session: AsyncSession,
    method_name: str,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign_friend = await _friend(session, other.id, "Other friend")
    subscription = await _subscription(session, owner.id)
    service = ChargeService(session)
    tx, _next_date, _estimated, _actual = await service.confirm_charged(
        subscription,
        user_id=owner.id,
    )
    await SubscriptionRepository(session).add_participant(
        subscription_id=subscription.id,
        friend_id=foreign_friend.id,
    )
    tx_id = tx.id
    owner_id = owner.id
    foreign_friend_id = foreign_friend.id
    foreign_friend_before = _column_snapshot(foreign_friend)
    await session.commit()
    session.expire_all()
    tx = await service.get_for_user(tx_id, owner_id)
    assert tx is not None
    assert tx.subscription is not None
    tx_before = _column_snapshot(tx)
    subscription_before = _column_snapshot(tx.subscription)
    counts_before = (
        await _count(session, Transaction),
        await _count(session, TransactionSplit),
        await _count(session, Debt),
    )

    with pytest.raises(ChargeDataUnavailableError):
        if method_name == "update_actual_rub":
            await service.update_actual_rub(tx, Decimal("130"))
        elif method_name == "update_charge_date":
            await service.update_charge_date(tx, date(2026, 7, 20))
        elif method_name == "update_rate":
            await service.update_rate(tx, Decimal("1.10"))
        else:
            await service.recalculate_debts(tx)

    assert _column_snapshot(tx) == tx_before
    assert _column_snapshot(tx.subscription) == subscription_before
    loaded_foreign_friend = await session.get(Friend, foreign_friend_id)
    assert loaded_foreign_friend is not None
    assert _column_snapshot(loaded_foreign_friend) == foreign_friend_before
    assert (
        await _count(session, Transaction),
        await _count(session, TransactionSplit),
        await _count(session, Debt),
    ) == counts_before


def _period_cb(subscription: Subscription) -> SubPeriodCb:
    assert subscription.next_charge_date is not None
    return SubPeriodCb(
        action="charged",
        sid=subscription.id,
        period=subscription.next_charge_date.strftime("%Y%m%d"),
    )


@pytest.mark.asyncio
async def test_foreign_subscription_callback_does_not_confirm(
    session: AsyncSession,
) -> None:
    current_user = await _user(session, 1)
    other = await _user(session, 2)
    foreign_subscription = await _subscription(session, other.id)
    subscription_before = _column_snapshot(foreign_subscription)
    callback = _callback()
    state = AsyncMock()

    await cb_charged(
        callback,
        _period_cb(foreign_subscription),
        state,
        session,
        current_user,
    )

    await _assert_no_charge_records(session)
    assert _column_snapshot(foreign_subscription) == subscription_before
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        "Подписка не найдена",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_missing_subscription_callback_has_same_neutral_response(
    session: AsyncSession,
) -> None:
    current_user = await _user(session, 1)
    callback = _callback()
    state = AsyncMock()

    await cb_charged(
        callback,
        SubPeriodCb(action="charged", sid=999_999, period="20260714"),
        state,
        session,
        current_user,
    )

    await _assert_no_charge_records(session)
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        "Подписка не найдена",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_handler_shows_neutral_message_for_invalid_nested_data(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign_method = await _payment_method(session, other.id, "Other card")
    subscription = await _subscription(session, owner.id)
    subscription.payment_method_id = foreign_method.id
    await session.flush()
    subscription = await _reload_subscription(session, subscription.id, owner.id)
    subscription_before = _column_snapshot(subscription)
    method_before = _column_snapshot(foreign_method)
    callback = _callback()
    state = AsyncMock()

    await cb_charged(
        callback,
        _period_cb(subscription),
        state,
        session,
        owner,
    )

    await _assert_no_charge_records(session)
    assert _column_snapshot(subscription) == subscription_before
    assert _column_snapshot(foreign_method) == method_before
    state.clear.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        CHARGE_DATA_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )
