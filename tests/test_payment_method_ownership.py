"""Security: payment_method_id must belong to the creating user."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.handlers.one_time_payments import ot_confirm, ot_pm
from app.handlers.subscriptions import add_payment_method, confirm_create
from app.models import Base
from app.models.debt import Debt
from app.models.enums import (
    BillingType,
    ConversionMode,
    CurrencyCode,
    SplitMode,
    SubscriptionCategory,
    TransactionType,
)
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit
from app.models.user import User
from app.repositories.payment_methods import (
    PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
    PaymentMethodRepository,
    PaymentMethodUnavailableError,
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


async def _user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    username: str = "u",
) -> User:
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=username,
        first_name=username.upper(),
    )
    return user


async def _pm(session: AsyncSession, user_id: int, *, name: str = "Card") -> PaymentMethod:
    return await PaymentMethodRepository(session).create(user_id=user_id, name=name)


def _sub_dto(user_id: int, payment_method_id: int | None) -> CreateSubscriptionDTO:
    return CreateSubscriptionDTO(
        user_id=user_id,
        name="ChatGPT Plus",
        category=SubscriptionCategory.AI_WORK.value,
        amount=Decimal("20"),
        currency="USD",
        billing_type=BillingType.MONTHLY.value,
        billing_interval=None,
        billing_day=20,
        next_charge_date=date(2026, 7, 20),
        payment_method_id=payment_method_id,
        reminder_offsets=[3, 1, 0],
        reminder_time="10:00",
        friend_ids=[],
    )


def _ot_dto(
    user_id: int,
    payment_method_id: int | None,
    *,
    friend_ids: list[int] | None = None,
    split_mode: str | None = None,
) -> CreateOneTimePaymentDTO:
    return CreateOneTimePaymentDTO(
        user_id=user_id,
        name="Отель",
        category=SubscriptionCategory.OTHER.value,
        original_amount=Decimal("1000"),
        original_currency=CurrencyCode.RUB.value,
        transaction_date=date(2026, 7, 14),
        payment_method_id=payment_method_id,
        conversion_mode=ConversionMode.ACTUAL_RUB.value,
        actual_rub_amount=Decimal("1000"),
        include_owner_in_split=True,
        split_mode=split_mode,
        friend_ids=friend_ids or [],
    )


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


# ── SubscriptionService.create ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_subscription_own_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    method = await _pm(session, owner.id, name="Моя карта")

    sub = await SubscriptionService(session).create(_sub_dto(owner.id, method.id))
    await session.commit()

    assert sub.id is not None
    assert sub.payment_method_id == method.id


@pytest.mark.asyncio
async def test_create_subscription_rejects_foreign_payment_method(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id, name="Чужая карта")

    with pytest.raises(PaymentMethodUnavailableError) as exc_info:
        await SubscriptionService(session).create(_sub_dto(owner.id, foreign.id))

    assert str(exc_info.value) == PAYMENT_METHOD_UNAVAILABLE_MESSAGE
    assert await _count(session, Subscription) == 0
    assert await _count(session, SubscriptionParticipant) == 0
    reloaded = await PaymentMethodRepository(session).get_for_user(foreign.id, other.id)
    assert reloaded is not None
    assert reloaded.user_id == other.id
    assert reloaded.name == "Чужая карта"


@pytest.mark.asyncio
async def test_create_subscription_rejects_missing_payment_method(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")

    with pytest.raises(PaymentMethodUnavailableError):
        await SubscriptionService(session).create(_sub_dto(owner.id, 999_999))

    assert await _count(session, Subscription) == 0


@pytest.mark.asyncio
async def test_create_subscription_allows_none_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")

    sub = await SubscriptionService(session).create(_sub_dto(owner.id, None))
    await session.commit()

    assert sub.id is not None
    assert sub.payment_method_id is None


@pytest.mark.asyncio
async def test_create_subscription_rejects_inactive_payment_method(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    method = await _pm(session, owner.id, name="Старая")
    await PaymentMethodRepository(session).deactivate(method)

    with pytest.raises(PaymentMethodUnavailableError):
        await SubscriptionService(session).create(_sub_dto(owner.id, method.id))

    assert await _count(session, Subscription) == 0


@pytest.mark.asyncio
async def test_create_subscription_foreign_pm_creates_no_participants(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id)
    friend = Friend(user_id=owner.id, name="Катя")
    session.add(friend)
    await session.flush()

    dto = _sub_dto(owner.id, foreign.id)
    dto.friend_ids = [friend.id]

    with pytest.raises(PaymentMethodUnavailableError):
        await SubscriptionService(session).create(dto)

    assert await _count(session, Subscription) == 0
    assert await _count(session, SubscriptionParticipant) == 0


# ── TransactionService.create_one_time ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_one_time_own_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    method = await _pm(session, owner.id)

    tx = await TransactionService(session).create_one_time(_ot_dto(owner.id, method.id))
    await session.commit()

    assert tx.id is not None
    assert tx.payment_method_id == method.id
    assert tx.transaction_type == TransactionType.ONE_TIME.value


@pytest.mark.asyncio
async def test_create_one_time_rejects_foreign_payment_method_no_debts(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id)
    friend = Friend(user_id=owner.id, name="Катя")
    session.add(friend)
    await session.flush()

    with pytest.raises(PaymentMethodUnavailableError) as exc_info:
        await TransactionService(session).create_one_time(
            _ot_dto(
                owner.id,
                foreign.id,
                friend_ids=[friend.id],
                split_mode=SplitMode.EQUAL.value,
            )
        )

    assert str(exc_info.value) == PAYMENT_METHOD_UNAVAILABLE_MESSAGE
    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0
    reloaded = await PaymentMethodRepository(session).get_for_user(foreign.id, other.id)
    assert reloaded is not None
    assert reloaded.user_id == other.id


@pytest.mark.asyncio
async def test_create_one_time_rejects_missing_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")

    with pytest.raises(PaymentMethodUnavailableError):
        await TransactionService(session).create_one_time(_ot_dto(owner.id, 999_999))

    assert await _count(session, Transaction) == 0
    assert await _count(session, Debt) == 0


@pytest.mark.asyncio
async def test_create_one_time_allows_none_payment_method(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")

    tx = await TransactionService(session).create_one_time(_ot_dto(owner.id, None))
    await session.commit()

    assert tx.id is not None
    assert tx.payment_method_id is None


# ── Handler / FSM ────────────────────────────────────────────────────────────


def _confirm_callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_subscription_pm_callback_rejects_foreign_id_before_fsm_write(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id)
    state = AsyncMock()
    callback = _confirm_callback()

    await add_payment_method(
        callback,
        MenuCb(action="pm", value=str(foreign.id)),
        state,
        session,
        owner,
    )

    state.update_data.assert_not_awaited()
    state.set_state.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_one_time_pm_callback_rejects_inactive_id_before_fsm_write(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    inactive = await _pm(session, owner.id)
    await PaymentMethodRepository(session).deactivate(inactive)
    state = AsyncMock()
    callback = _confirm_callback()

    await ot_pm(
        callback,
        MenuCb(action="pm", value=str(inactive.id)),
        state,
        session,
        owner,
    )

    state.update_data.assert_not_awaited()
    state.set_state.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_confirm_create_subscription_rejects_foreign_pm_resets_fsm(
    session: AsyncSession,
) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id)

    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "Netflix",
            "category": SubscriptionCategory.AI_WORK.value,
            "amount": "15",
            "currency": "USD",
            "billing_type": BillingType.MONTHLY.value,
            "billing_interval": None,
            "billing_day": 10,
            "next_charge_date": "2026-08-10",
            "payment_method_id": foreign.id,
            "reminder_offsets": [1],
            "reminder_time": "10:00",
            "friend_ids": [],
        }
    )
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()

    callback = _confirm_callback()
    callback_data = MenuCb(action="sub_confirm", value="yes")

    await confirm_create(callback, callback_data, state, session, owner)

    assert await _count(session, Subscription) == 0
    state.clear.assert_not_awaited()
    state.update_data.assert_awaited_with(payment_method_id=None)
    state.set_state.assert_awaited_with(AddSubscriptionSG.payment_method)
    callback.message.edit_text.assert_awaited()
    edit_kwargs = callback.message.edit_text.await_args
    assert edit_kwargs.args[0] == PAYMENT_METHOD_UNAVAILABLE_MESSAGE
    assert edit_kwargs.kwargs.get("reply_markup") is not None
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_ot_confirm_rejects_foreign_pm_resets_fsm(session: AsyncSession) -> None:
    owner = await _user(session, telegram_user_id=1, username="owner")
    other = await _user(session, telegram_user_id=2, username="other")
    foreign = await _pm(session, other.id)

    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "name": "Отель",
            "amount": "1000",
            "currency": CurrencyCode.RUB.value,
            "payment_date": "2026-07-14",
            "payment_method_id": foreign.id,
            "selected_friend_ids": [],
            "include_owner": True,
            "split_mode": None,
        }
    )
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()

    callback = _confirm_callback()
    callback_data = MenuCb(action="pay_confirm", value="yes")

    await ot_confirm(callback, callback_data, state, session, owner)

    assert await _count(session, Transaction) == 0
    assert await _count(session, Debt) == 0
    state.clear.assert_not_awaited()
    state.update_data.assert_awaited_with(payment_method_id=None)
    state.set_state.assert_awaited_with(OneTimePaymentSG.payment_method)
    callback.answer.assert_awaited_with(
        PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
        show_alert=True,
    )
