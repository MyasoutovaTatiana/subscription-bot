"""IDOR regression tests for mutation-entry callback buttons."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.handlers.charges import cb_tx_amt, cb_tx_date, cb_tx_del_ask, cb_tx_undo_ask
from app.handlers.debts import cb_edit as cb_debt_edit
from app.handlers.subscriptions import (
    cb_chg_amt,
    cb_chg_date,
    cb_delete_ask,
    cb_edit_field,
    cb_edit_menu,
    cb_prob_del,
    cb_prob_new_date,
    cb_prob_price,
)
from app.models import Base
from app.models.debt import Debt
from app.models.enums import BillingType, DebtStatus, SubscriptionCategory, TransactionType
from app.models.friend import Friend
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User
from app.utils.callback_data import DebtCb, SubCb, TxCb


@pytest_asyncio.fixture
async def security_context(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'callback-ownership.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        current = User(telegram_user_id=101, telegram_chat_id=101, first_name="Current")
        foreign = User(telegram_user_id=202, telegram_chat_id=202, first_name="Foreign")
        session.add_all([current, foreign])
        await session.flush()

        subscription = Subscription(
            user_id=foreign.id,
            name="Foreign subscription",
            category=SubscriptionCategory.OTHER.value,
            amount=Decimal("100"),
            currency="RUB",
            billing_type=BillingType.MONTHLY.value,
            billing_day=22,
            next_charge_date=date(2026, 7, 22),
            reminder_offsets=[1, 0],
            reminder_time="10:00",
        )
        friend = Friend(user_id=foreign.id, name="Foreign friend")
        session.add_all([subscription, friend])
        await session.flush()

        transaction = Transaction(
            user_id=foreign.id,
            subscription_id=subscription.id,
            transaction_type=TransactionType.SUBSCRIPTION.value,
            name=subscription.name,
            category=subscription.category,
            original_amount=subscription.amount,
            original_currency=subscription.currency,
            estimated_rub_amount=Decimal("100"),
            transaction_date=date(2026, 7, 22),
        )
        session.add(transaction)
        await session.flush()

        debt = Debt(
            user_id=foreign.id,
            transaction_id=transaction.id,
            friend_id=friend.id,
            amount_rub=Decimal("50"),
            status=DebtStatus.ACTIVE.value,
        )
        session.add(debt)
        await session.flush()

        yield SimpleNamespace(
            session=session,
            current=current,
            subscription=subscription,
            transaction=transaction,
            debt=debt,
        )
    await engine.dispose()


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "action"),
    [
        (cb_delete_ask, "del"),
        (cb_edit_menu, "edit"),
        (cb_prob_del, "prob_del"),
    ],
)
async def test_foreign_subscription_never_opens_mutation_confirmation(
    security_context,
    handler,
    action: str,
) -> None:
    ctx = security_context
    callback = _callback()

    await handler(
        callback,
        SubCb(action=action, sid=ctx.subscription.id),
        ctx.session,
        ctx.current,
    )

    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Подписка не найдена", show_alert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "action"),
    [
        (cb_edit_field, "ef_amount"),
        (cb_prob_new_date, "prob_date"),
        (cb_prob_price, "prob_price"),
        (cb_chg_amt, "chg_amt"),
        (cb_chg_date, "chg_date"),
    ],
)
async def test_foreign_subscription_id_is_not_saved_to_fsm(
    security_context,
    handler,
    action: str,
) -> None:
    ctx = security_context
    callback = _callback()
    state = AsyncMock()

    await handler(
        callback,
        SubCb(action=action, sid=ctx.subscription.id),
        state,
        ctx.session,
        ctx.current,
    )

    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Подписка не найдена", show_alert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "action"),
    [
        (cb_tx_undo_ask, "undo"),
        (cb_tx_del_ask, "del"),
    ],
)
async def test_foreign_charge_never_opens_mutation_confirmation(
    security_context,
    handler,
    action: str,
) -> None:
    ctx = security_context
    callback = _callback()

    await handler(
        callback,
        TxCb(action=action, tid=ctx.transaction.id),
        ctx.session,
        ctx.current,
    )

    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Списание не найдено", show_alert=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "action"),
    [
        (cb_tx_amt, "amt"),
        (cb_tx_date, "date"),
    ],
)
async def test_foreign_charge_id_is_not_saved_to_fsm(
    security_context,
    handler,
    action: str,
) -> None:
    ctx = security_context
    callback = _callback()
    state = AsyncMock()

    await handler(
        callback,
        TxCb(action=action, tid=ctx.transaction.id),
        state,
        ctx.session,
        ctx.current,
    )

    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Списание не найдено", show_alert=True)


@pytest.mark.asyncio
async def test_foreign_debt_id_is_not_saved_to_fsm(security_context) -> None:
    ctx = security_context
    callback = _callback()
    state = AsyncMock()

    await cb_debt_edit(
        callback,
        DebtCb(action="edit", did=ctx.debt.id),
        state,
        ctx.session,
        ctx.current,
    )

    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with("Долг не найден", show_alert=True)
