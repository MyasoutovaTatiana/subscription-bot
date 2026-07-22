"""Security checks for owner-scoped debt mutations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.models import Base
from app.models.debt import Debt
from app.models.enums import DebtStatus, TransactionType
from app.models.friend import Friend
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.debts import DebtRepository


@pytest_asyncio.fixture
async def debt_context(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'debt-ownership.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        owner = User(telegram_user_id=101, telegram_chat_id=101, first_name="Owner")
        attacker = User(telegram_user_id=202, telegram_chat_id=202, first_name="Attacker")
        session.add_all([owner, attacker])
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
            share_token=None,
        )
        session.add(debt)
        await session.commit()
        ids = SimpleNamespace(owner=owner.id, attacker=attacker.id, debt=debt.id)

    yield SimpleNamespace(factory=factory, ids=ids)
    await engine.dispose()


async def _prepare(session: AsyncSession, debt: Debt, operation: str) -> None:
    if operation in {"reopen", "remind"}:
        debt.status = DebtStatus.NEEDS_REVIEW.value
        await session.flush()


async def _mutate(
    repo: DebtRepository,
    debt: Debt,
    operation: str,
    *,
    user_id: int,
):
    if operation == "share":
        return await repo.ensure_share_token(debt, user_id=user_id)
    if operation == "paid":
        return await repo.mark_paid(debt, user_id=user_id)
    if operation == "reopen":
        return await repo.reopen_awaiting(debt, user_id=user_id)
    if operation == "remind":
        return await repo.schedule_review_reminder(debt, user_id=user_id)
    if operation == "cancel":
        return await repo.cancel(debt, user_id=user_id)
    return await repo.update_amount(debt, Decimal("999"), user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["share", "paid", "reopen", "remind", "cancel", "amount"],
)
async def test_foreign_debt_mutation_is_rejected(debt_context, operation: str) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        repo = DebtRepository(session)
        debt = await repo.get_by_id(ids.debt)
        assert debt is not None
        await _prepare(session, debt, operation)
        await session.commit()
        expected_status = debt.status

        result = await _mutate(repo, debt, operation, user_id=ids.attacker)
        await session.commit()

        assert result is None if operation == "share" else result is False
        session.expire_all()
        unchanged = await repo.get_by_id(ids.debt)
        assert unchanged is not None
        assert unchanged.status == expected_status
        assert unchanged.amount_rub == Decimal("500.00")
        assert unchanged.share_token is None
        assert unchanged.review_remind_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["share", "paid", "reopen", "remind", "cancel", "amount"],
)
async def test_owner_can_mutate_debt(debt_context, operation: str) -> None:
    factory, ids = debt_context.factory, debt_context.ids
    async with factory() as session:
        repo = DebtRepository(session)
        debt = await repo.get_by_id(ids.debt)
        assert debt is not None
        await _prepare(session, debt, operation)

        result = await _mutate(repo, debt, operation, user_id=ids.owner)
        await session.commit()

        assert result is not None if operation == "share" else result is True
        session.expire_all()
        changed = await repo.get_by_id(ids.debt)
        assert changed is not None
        if operation == "share":
            assert changed.share_token
        elif operation == "paid":
            assert changed.status == DebtStatus.PAID.value
        elif operation == "reopen":
            assert changed.status == DebtStatus.ACTIVE.value
        elif operation == "remind":
            assert changed.review_remind_at is not None
        elif operation == "cancel":
            assert changed.status == DebtStatus.CANCELLED.value
        else:
            assert changed.amount_rub == Decimal("999.00")
