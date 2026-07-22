"""Security regression tests for stale and concurrent debt actions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.handlers.debts import cb_cancel, cb_money_no, cb_money_ok, edit_debt_amount
from app.models import Base
from app.models.debt import Debt
from app.models.enums import DebtStatus, TransactionType
from app.models.friend import Friend
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.debts import DebtRepository
from app.utils.callback_data import DebtCb


@pytest_asyncio.fixture
async def debt_context(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'debt-transitions.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        owner = User(
            telegram_user_id=101,
            telegram_chat_id=101,
            first_name="Owner",
        )
        payer = User(
            telegram_user_id=202,
            telegram_chat_id=202,
            first_name="Payer",
        )
        session.add_all([owner, payer])
        await session.flush()
        friend = Friend(user_id=owner.id, name="Друг")
        session.add(friend)
        await session.flush()
        transaction = Transaction(
            user_id=owner.id,
            transaction_type=TransactionType.ONE_TIME.value,
            name="Ужин",
            original_amount=Decimal("1000"),
            original_currency="RUB",
            estimated_rub_amount=Decimal("1000"),
            transaction_date=date(2026, 7, 22),
        )
        session.add(transaction)
        await session.flush()
        debt = Debt(
            user_id=owner.id,
            transaction_id=transaction.id,
            friend_id=friend.id,
            amount_rub=Decimal("500"),
            status=DebtStatus.ACTIVE.value,
            payer_telegram_id=payer.telegram_user_id,
        )
        session.add(debt)
        await session.commit()
        ids = SimpleNamespace(owner=owner.id, payer=payer.id, debt=debt.id)

    yield SimpleNamespace(factory=factory, ids=ids)
    await engine.dispose()


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


async def _load_users(session: AsyncSession, ids):
    owner = await session.get(User, ids.owner)
    payer = await session.get(User, ids.payer)
    assert owner is not None and payer is not None
    return owner, payer


@pytest.mark.asyncio
async def test_only_first_concurrent_friend_report_wins(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as first, factory() as stale:
        first_debt = await DebtRepository(first).get_by_id(ids.debt)
        stale_debt = await DebtRepository(stale).get_by_id(ids.debt)
        assert first_debt is not None and stale_debt is not None

        first_won = await DebtRepository(first).mark_payment_reported(
            first_debt,
            payer_telegram_id=202,
        )
        await first.commit()
        stale_won = await DebtRepository(stale).mark_payment_reported(
            stale_debt,
            payer_telegram_id=202,
        )
        await stale.commit()

    assert first_won is True
    assert stale_won is False
    async with factory() as verify:
        debt = await DebtRepository(verify).get_by_id(ids.debt)
        assert debt is not None
        assert debt.status == DebtStatus.NEEDS_REVIEW.value


@pytest.mark.asyncio
async def test_cancelled_debt_cannot_be_closed_by_stale_button(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as cancel_session, factory() as stale:
        cancelled = await DebtRepository(cancel_session).get_by_id(ids.debt)
        stale_debt = await DebtRepository(stale).get_by_id(ids.debt)
        assert cancelled is not None and stale_debt is not None
        assert await DebtRepository(cancel_session).cancel(cancelled, user_id=ids.owner) is True
        await cancel_session.commit()
        assert await DebtRepository(stale).mark_paid(stale_debt, user_id=ids.owner) is False
        await stale.commit()

    async with factory() as verify:
        debt = await DebtRepository(verify).get_by_id(ids.debt)
        assert debt is not None
        assert debt.status == DebtStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_paid_debt_cannot_be_reopened_by_stale_button(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as setup:
        debt = await DebtRepository(setup).get_by_id(ids.debt)
        assert debt is not None
        assert await DebtRepository(setup).mark_payment_reported(
            debt,
            payer_telegram_id=202,
        ) is True
        await setup.commit()

    async with factory() as paid_session, factory() as stale:
        paid_debt = await DebtRepository(paid_session).get_by_id(ids.debt)
        stale_debt = await DebtRepository(stale).get_by_id(ids.debt)
        assert paid_debt is not None and stale_debt is not None
        assert await DebtRepository(paid_session).mark_paid(paid_debt, user_id=ids.owner) is True
        await paid_session.commit()
        assert await DebtRepository(stale).reopen_awaiting(
            stale_debt,
            user_id=ids.owner,
        ) is False
        await stale.commit()

    async with factory() as verify:
        debt = await DebtRepository(verify).get_by_id(ids.debt)
        assert debt is not None
        assert debt.status == DebtStatus.PAID.value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DebtStatus.PAID.value, DebtStatus.CANCELLED.value])
async def test_closed_debt_amount_cannot_be_changed(debt_context, status: str) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        debt = await DebtRepository(session).get_by_id(ids.debt)
        assert debt is not None
        debt.status = status
        await session.commit()

    async with factory() as session:
        owner, _ = await _load_users(session, ids)
        message = MagicMock(text="999")
        message.answer = AsyncMock()
        state = AsyncMock()
        state.get_data.return_value = {"debt_id": ids.debt}

        await edit_debt_amount(message, state, session, owner)
        await session.commit()

        debt = await DebtRepository(session).get_by_id(ids.debt)
        assert debt is not None
        assert debt.amount_rub == Decimal("500.00")
        message.answer.assert_awaited_once()
        assert "закрыт или отменён" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_stale_money_no_does_not_reopen_paid_debt(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        owner, _ = await _load_users(session, ids)
        debt = await DebtRepository(session).get_by_id(ids.debt)
        assert debt is not None
        debt.status = DebtStatus.PAID.value
        await session.commit()
        callback = _callback()

        await cb_money_no(
            callback,
            DebtCb(action="money_no", did=ids.debt),
            session,
            owner,
            AsyncMock(),
        )

        refreshed = await DebtRepository(session).get_by_id(ids.debt)
        assert refreshed is not None
        assert refreshed.status == DebtStatus.PAID.value
        callback.answer.assert_awaited_once_with(
            "Статус долга уже изменён",
            show_alert=True,
        )


@pytest.mark.asyncio
async def test_owner_stale_cancel_does_not_cancel_review_debt(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        owner, _ = await _load_users(session, ids)
        debt = await DebtRepository(session).get_by_id(ids.debt)
        assert debt is not None
        debt.status = DebtStatus.NEEDS_REVIEW.value
        await session.commit()
        callback = _callback()

        await cb_cancel(
            callback,
            DebtCb(action="cancel", did=ids.debt),
            session,
            owner,
        )

        refreshed = await DebtRepository(session).get_by_id(ids.debt)
        assert refreshed is not None
        assert refreshed.status == DebtStatus.NEEDS_REVIEW.value
        callback.answer.assert_awaited_once_with(
            "Статус долга уже изменён",
            show_alert=True,
        )


@pytest.mark.asyncio
async def test_owner_stale_money_ok_does_not_close_cancelled_debt(debt_context) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        owner, _ = await _load_users(session, ids)
        debt = await DebtRepository(session).get_by_id(ids.debt)
        assert debt is not None
        debt.status = DebtStatus.CANCELLED.value
        await session.commit()
        callback = _callback()

        await cb_money_ok(
            callback,
            DebtCb(action="money_ok", did=ids.debt),
            session,
            owner,
            AsyncMock(),
        )

        refreshed = await DebtRepository(session).get_by_id(ids.debt)
        assert refreshed is not None
        assert refreshed.status == DebtStatus.CANCELLED.value
        callback.answer.assert_awaited_once_with(
            "Статус долга уже изменён",
            show_alert=True,
        )
