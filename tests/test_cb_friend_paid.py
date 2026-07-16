"""Security tests for cb_friend_paid access control and status transitions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.handlers.debts import cb_friend_paid
from app.models import Base
from app.models.debt import Debt
from app.models.enums import DebtStatus, TransactionType
from app.models.friend import Friend
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.debts import DebtRepository
from app.utils.callback_data import DebtCb


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _owner(session: AsyncSession) -> User:
    user = User(
        telegram_user_id=1001,
        telegram_chat_id=1001,
        username="owner",
        first_name="Owner",
    )
    session.add(user)
    await session.flush()
    return user


async def _actor(session: AsyncSession, *, telegram_user_id: int = 2002) -> User:
    user = User(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username="friend",
        first_name="Friend",
    )
    session.add(user)
    await session.flush()
    return user


async def _make_debt(
    session: AsyncSession,
    owner: User,
    *,
    status: str = DebtStatus.ACTIVE.value,
    payer_telegram_id: int | None = None,
) -> Debt:
    friend = Friend(user_id=owner.id, name="Катя")
    session.add(friend)
    await session.flush()

    tx = Transaction(
        user_id=owner.id,
        transaction_type=TransactionType.ONE_TIME.value,
        name="Ужин",
        original_amount=Decimal("1000"),
        original_currency="RUB",
        estimated_rub_amount=Decimal("1000"),
        is_rate_estimated=False,
        transaction_date=date(2026, 7, 14),
    )
    session.add(tx)
    await session.flush()

    debt = await DebtRepository(session).create(
        user_id=owner.id,
        transaction_id=tx.id,
        friend_id=friend.id,
        amount_rub=Decimal("500.00"),
        status=status,
        payer_telegram_id=payer_telegram_id,
    )
    await session.commit()
    return await DebtRepository(session).get_by_id(debt.id)


def _callback(debt_id: int) -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


def _callback_data(debt_id: int) -> DebtCb:
    return DebtCb(action="friend_paid", did=debt_id)


@pytest.mark.asyncio
async def test_friend_paid_denies_when_payer_unbound(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session)
    debt = await _make_debt(session, owner, payer_telegram_id=None)
    bot = AsyncMock()
    callback = _callback(debt.id)

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.ACTIVE.value
    assert refreshed.payer_telegram_id is None
    callback.answer.assert_awaited_once_with("Нет доступа", show_alert=True)
    bot.send_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_friend_paid_denies_when_payer_is_another_user(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session, telegram_user_id=2002)
    debt = await _make_debt(
        session,
        owner,
        status=DebtStatus.ACTIVE.value,
        payer_telegram_id=9999,
    )
    bot = AsyncMock()
    callback = _callback(debt.id)
    original_payer = debt.payer_telegram_id

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.ACTIVE.value
    assert refreshed.payer_telegram_id == original_payer
    callback.answer.assert_awaited_once_with("Нет доступа", show_alert=True)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_friend_paid_active_to_needs_review_notifies_once(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session, telegram_user_id=2002)
    debt = await _make_debt(
        session,
        owner,
        status=DebtStatus.ACTIVE.value,
        payer_telegram_id=actor.telegram_user_id,
    )
    bot = AsyncMock()
    callback = _callback(debt.id)

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.NEEDS_REVIEW.value
    assert refreshed.payer_telegram_id == actor.telegram_user_id
    assert refreshed.payment_reported_at is not None
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == owner.telegram_chat_id
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_friend_paid_needs_review_is_idempotent(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session, telegram_user_id=2002)
    debt = await _make_debt(
        session,
        owner,
        status=DebtStatus.NEEDS_REVIEW.value,
        payer_telegram_id=actor.telegram_user_id,
    )
    reported_at = debt.payment_reported_at
    bot = AsyncMock()
    callback = _callback(debt.id)

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.NEEDS_REVIEW.value
    assert refreshed.payer_telegram_id == actor.telegram_user_id
    assert refreshed.payment_reported_at == reported_at
    callback.answer.assert_awaited_once_with("Информация уже отправлена", show_alert=True)
    bot.send_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_friend_paid_paid_unchanged(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session, telegram_user_id=2002)
    debt = await _make_debt(
        session,
        owner,
        status=DebtStatus.PAID.value,
        payer_telegram_id=actor.telegram_user_id,
    )
    bot = AsyncMock()
    callback = _callback(debt.id)

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.PAID.value
    assert refreshed.payer_telegram_id == actor.telegram_user_id
    callback.answer.assert_awaited_once_with("Долг уже закрыт", show_alert=True)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_friend_paid_cancelled_unchanged(session: AsyncSession) -> None:
    owner = await _owner(session)
    actor = await _actor(session, telegram_user_id=2002)
    debt = await _make_debt(
        session,
        owner,
        status=DebtStatus.CANCELLED.value,
        payer_telegram_id=actor.telegram_user_id,
    )
    bot = AsyncMock()
    callback = _callback(debt.id)

    await cb_friend_paid(callback, _callback_data(debt.id), session, actor, bot)

    refreshed = await DebtRepository(session).get_by_id(debt.id)
    assert refreshed is not None
    assert refreshed.status == DebtStatus.CANCELLED.value
    assert refreshed.status != DebtStatus.NEEDS_REVIEW.value
    assert refreshed.payer_telegram_id == actor.telegram_user_id
    callback.answer.assert_awaited_once_with("Долг отменён", show_alert=True)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_friend_paid_missing_debt_handled(session: AsyncSession) -> None:
    actor = await _actor(session)
    bot = AsyncMock()
    callback = _callback(999_999)

    await cb_friend_paid(callback, _callback_data(999_999), session, actor, bot)

    callback.answer.assert_awaited_once_with("Не найдено", show_alert=True)
    bot.send_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
