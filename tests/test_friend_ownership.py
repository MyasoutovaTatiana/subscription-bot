"""Security: friend_id must belong to the user creating an operation."""

from __future__ import annotations

import gc
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.handlers.one_time_payments import (
    PAYMENT_SAVE_ERROR_MESSAGE,
    ot_confirm,
    ot_friends_toggle,
)
from app.handlers.subscriptions import confirm_create
from app.models import Base
from app.models.debt import Debt
from app.models.enums import (
    BillingType,
    ConversionMode,
    CurrencyCode,
    SplitMode,
    SubscriptionCategory,
)
from app.models.friend import Friend
from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit
from app.models.user import User
from app.repositories.friends import (
    FRIENDS_UNAVAILABLE_MESSAGE,
    FriendRepository,
    FriendsUnavailableError,
)
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
from app.services.transactions import CreateOneTimePaymentDTO, TransactionService
from app.services.users import UserService
from app.states.payments import OneTimePaymentSG
from app.states.subscriptions import AddSubscriptionSG
from app.utils.callback_data import MenuCb


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user(session: AsyncSession, telegram_user_id: int) -> User:
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=f"user{telegram_user_id}",
        first_name=f"User {telegram_user_id}",
    )
    return user


async def _friend(session: AsyncSession, user_id: int, name: str) -> Friend:
    return await FriendRepository(session).create(user_id=user_id, name=name)


def _subscription_dto(user_id: int, friend_ids: list[int]) -> CreateSubscriptionDTO:
    return CreateSubscriptionDTO(
        user_id=user_id,
        name="Общая подписка",
        category=SubscriptionCategory.AI_WORK.value,
        amount=Decimal("900"),
        currency=CurrencyCode.RUB.value,
        billing_type=BillingType.MONTHLY.value,
        billing_interval=None,
        billing_day=20,
        next_charge_date=date(2026, 8, 20),
        payment_method_id=None,
        reminder_offsets=[1],
        reminder_time="10:00",
        friend_ids=friend_ids,
    )


def _one_time_dto(user_id: int, friend_ids: list[int]) -> CreateOneTimePaymentDTO:
    return CreateOneTimePaymentDTO(
        user_id=user_id,
        name="Ужин",
        category=SubscriptionCategory.OTHER.value,
        original_amount=Decimal("900"),
        original_currency=CurrencyCode.RUB.value,
        transaction_date=date(2026, 7, 14),
        payment_method_id=None,
        conversion_mode=ConversionMode.ACTUAL_RUB.value,
        actual_rub_amount=Decimal("900"),
        include_owner_in_split=True,
        split_mode=SplitMode.EQUAL.value if friend_ids else None,
        friend_ids=friend_ids,
    )


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def _assert_no_subscription_records(session: AsyncSession) -> None:
    assert await _count(session, Subscription) == 0
    assert await _count(session, SubscriptionParticipant) == 0


async def _assert_no_one_time_records(session: AsyncSession) -> None:
    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0


@pytest.mark.asyncio
async def test_subscription_accepts_owned_friends(session: AsyncSession) -> None:
    owner = await _user(session, 1)
    friends = [
        await _friend(session, owner.id, "Катя"),
        await _friend(session, owner.id, "Миша"),
    ]

    sub = await SubscriptionService(session).create(
        _subscription_dto(owner.id, [friend.id for friend in friends])
    )

    assert {participant.friend_id for participant in sub.participants} == {
        friend.id for friend in friends
    }
    assert await _count(session, Subscription) == 1
    assert await _count(session, SubscriptionParticipant) == 2


@pytest.mark.asyncio
async def test_subscription_rejects_foreign_friend(session: AsyncSession) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")

    with pytest.raises(FriendsUnavailableError, match=FRIENDS_UNAVAILABLE_MESSAGE):
        await SubscriptionService(session).create(
            _subscription_dto(owner.id, [foreign.id])
        )

    await _assert_no_subscription_records(session)
    assert await FriendRepository(session).get_for_user(foreign.id, other.id) is not None


@pytest.mark.asyncio
async def test_subscription_rejects_missing_friend(session: AsyncSession) -> None:
    owner = await _user(session, 1)

    with pytest.raises(FriendsUnavailableError):
        await SubscriptionService(session).create(
            _subscription_dto(owner.id, [999_999])
        )

    await _assert_no_subscription_records(session)


@pytest.mark.asyncio
async def test_subscription_rejects_mixed_friends_atomically(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    own = await _friend(session, owner.id, "Свой друг")
    foreign = await _friend(session, other.id, "Чужой друг")

    with pytest.raises(FriendsUnavailableError):
        await SubscriptionService(session).create(
            _subscription_dto(owner.id, [own.id, foreign.id])
        )

    await _assert_no_subscription_records(session)


@pytest.mark.asyncio
async def test_subscription_allows_empty_friend_list(session: AsyncSession) -> None:
    owner = await _user(session, 1)

    sub = await SubscriptionService(session).create(
        _subscription_dto(owner.id, [])
    )

    assert sub.id is not None
    assert sub.participants == []
    assert await _count(session, Subscription) == 1
    assert await _count(session, SubscriptionParticipant) == 0


@pytest.mark.asyncio
async def test_one_time_accepts_owned_friends_and_creates_debts(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    friends = [
        await _friend(session, owner.id, "Катя"),
        await _friend(session, owner.id, "Миша"),
    ]

    tx = await TransactionService(session).create_one_time(
        _one_time_dto(owner.id, [friend.id for friend in friends])
    )

    assert tx.id is not None
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 3
    assert await _count(session, Debt) == 2
    debts = list((await session.execute(select(Debt))).scalars().all())
    assert {debt.friend_id for debt in debts} == {friend.id for friend in friends}
    assert {debt.amount_rub for debt in debts} == {Decimal("300.00")}


@pytest.mark.asyncio
async def test_one_time_rejects_foreign_friend(session: AsyncSession) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")

    with pytest.raises(FriendsUnavailableError, match=FRIENDS_UNAVAILABLE_MESSAGE):
        await TransactionService(session).create_one_time(
            _one_time_dto(owner.id, [foreign.id])
        )

    await _assert_no_one_time_records(session)
    assert await FriendRepository(session).get_for_user(foreign.id, other.id) is not None


@pytest.mark.asyncio
async def test_one_time_rejects_missing_friend(session: AsyncSession) -> None:
    owner = await _user(session, 1)

    with pytest.raises(FriendsUnavailableError):
        await TransactionService(session).create_one_time(
            _one_time_dto(owner.id, [999_999])
        )

    await _assert_no_one_time_records(session)


@pytest.mark.asyncio
async def test_one_time_rejects_mixed_friends_atomically(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    own = await _friend(session, owner.id, "Свой друг")
    foreign = await _friend(session, other.id, "Чужой друг")

    with pytest.raises(FriendsUnavailableError):
        await TransactionService(session).create_one_time(
            _one_time_dto(owner.id, [own.id, foreign.id])
        )

    await _assert_no_one_time_records(session)


@pytest.mark.asyncio
async def test_one_time_allows_empty_friend_list(session: AsyncSession) -> None:
    owner = await _user(session, 1)

    tx = await TransactionService(session).create_one_time(
        _one_time_dto(owner.id, [])
    )

    assert tx.id is not None
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_friend_toggle_rejects_foreign_id_before_fsm_write(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"selected_friend_ids": []})
    callback = _callback()

    await ot_friends_toggle(
        callback,
        MenuCb(action="ftoggle", value=str(foreign.id)),
        state,
        session,
        owner,
    )

    state.update_data.assert_not_awaited()
    state.set_state.assert_not_awaited()
    callback.message.edit_reply_markup.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        FRIENDS_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_done_rechecks_and_clears_foreign_friend_from_fsm(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"selected_friend_ids": [foreign.id]})
    callback = _callback()

    await ot_friends_toggle(
        callback,
        MenuCb(action="ftoggle", value="done"),
        state,
        session,
        owner,
    )

    state.update_data.assert_awaited_once_with(selected_friend_ids=[])
    state.set_state.assert_not_awaited()
    callback.message.edit_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once_with(
        FRIENDS_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_confirm_create_rejects_foreign_friend_and_returns_to_friends(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "Netflix",
            "category": SubscriptionCategory.AI_WORK.value,
            "amount": "900",
            "currency": CurrencyCode.RUB.value,
            "billing_type": BillingType.MONTHLY.value,
            "billing_interval": None,
            "billing_day": 20,
            "next_charge_date": "2026-08-20",
            "payment_method_id": None,
            "reminder_offsets": [1],
            "reminder_time": "10:00",
            "friend_ids": [foreign.id],
        }
    )
    callback = _callback()

    await confirm_create(
        callback,
        MenuCb(action="sub_confirm", value="yes"),
        state,
        session,
        owner,
    )

    await _assert_no_subscription_records(session)
    state.clear.assert_not_awaited()
    state.update_data.assert_awaited_with(friend_ids=[])
    state.set_state.assert_awaited_with(AddSubscriptionSG.friends)
    assert callback.message.edit_text.await_args.args[0] == FRIENDS_UNAVAILABLE_MESSAGE
    assert callback.message.edit_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_ot_confirm_rejects_foreign_friend_and_returns_to_friends(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    other = await _user(session, 2)
    foreign = await _friend(session, other.id, "Чужой друг")
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "Ужин",
            "amount": "900",
            "currency": CurrencyCode.RUB.value,
            "payment_date": "2026-07-14",
            "payment_method_id": None,
            "selected_friend_ids": [foreign.id],
            "include_owner": True,
            "split_mode": SplitMode.EQUAL.value,
        }
    )
    callback = _callback()

    await ot_confirm(
        callback,
        MenuCb(action="pay_confirm", value="yes"),
        state,
        session,
        owner,
    )

    await _assert_no_one_time_records(session)
    state.clear.assert_not_awaited()
    state.update_data.assert_awaited_with(selected_friend_ids=[])
    state.set_state.assert_awaited_with(OneTimePaymentSG.friends)
    assert callback.message.edit_text.await_args.args[0] == FRIENDS_UNAVAILABLE_MESSAGE
    assert callback.message.edit_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_ot_confirm_with_friends_saves_and_renders_success(
    session: AsyncSession,
) -> None:
    """Regression for #19: rendering debts must not trigger async lazy loading."""
    owner = await _user(session, 1)
    friends = [
        await _friend(session, owner.id, name)
        for name in ("Катя", "Миша", "Лена", "Олег")
    ]
    friend_ids = [friend.id for friend in friends]
    friend_names = [friend.name for friend in friends]
    # A production callback starts in a new update/session and only has FSM IDs.
    # Drop test-owned ORM references so Debt.friend cannot be satisfied from the
    # weak identity map by accident.
    del friends
    gc.collect()
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "тест",
            "amount": "1000",
            "currency": CurrencyCode.RUB.value,
            "payment_date": "2026-07-22",
            "payment_method_id": None,
            "selected_friend_ids": friend_ids,
            "include_owner": True,
            "split_mode": SplitMode.EQUAL.value,
        }
    )
    callback = _callback()

    await ot_confirm(
        callback,
        MenuCb(action="pay_confirm", value="yes"),
        state,
        session,
        owner,
    )

    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 5
    assert await _count(session, Debt) == 4
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    success_text = callback.message.edit_text.await_args.args[0]
    assert "Платёж сохранён" in success_text
    assert all(name in success_text for name in friend_names)
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_ot_confirm_reports_unexpected_save_error_and_allows_retry(
    session: AsyncSession,
) -> None:
    owner = await _user(session, 1)
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "тест",
            "amount": "1000",
            "currency": CurrencyCode.RUB.value,
            "payment_date": "2026-07-22",
            "payment_method_id": None,
            "selected_friend_ids": [],
            "include_owner": True,
            "split_mode": None,
        }
    )
    callback = _callback()

    with patch(
        "app.handlers.one_time_payments.TransactionService.create_one_time",
        new=AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        await ot_confirm(
            callback,
            MenuCb(action="pay_confirm", value="yes"),
            state,
            session,
            owner,
        )

    state.set_state.assert_has_awaits([call(None), call(OneTimePaymentSG.confirm)])
    state.clear.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        PAYMENT_SAVE_ERROR_MESSAGE,
        show_alert=True,
    )
