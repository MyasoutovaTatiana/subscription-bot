"""Atomicity regression tests for one-time payments and their debts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.debt import Debt
from app.models.enums import ConversionMode, CurrencyCode, SplitMode, SubscriptionCategory
from app.models.transaction import Transaction, TransactionSplit
from app.repositories.friends import FriendRepository
from app.services.transactions import CreateOneTimePaymentDTO, TransactionService
from app.services.users import UserService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _setup_payment(session: AsyncSession) -> CreateOneTimePaymentDTO:
    owner, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=1001,
        telegram_chat_id=1001,
        username="owner",
        first_name="Owner",
    )
    friends = [
        await FriendRepository(session).create(user_id=owner.id, name="Катя"),
        await FriendRepository(session).create(user_id=owner.id, name="Миша"),
    ]
    return CreateOneTimePaymentDTO(
        user_id=owner.id,
        name="Ужин",
        category=SubscriptionCategory.OTHER.value,
        original_amount=Decimal("900"),
        original_currency=CurrencyCode.RUB.value,
        transaction_date=date(2026, 7, 22),
        payment_method_id=None,
        conversion_mode=ConversionMode.ACTUAL_RUB.value,
        actual_rub_amount=Decimal("900"),
        include_owner_in_split=True,
        split_mode=SplitMode.EQUAL.value,
        friend_ids=[friend.id for friend in friends],
    )


async def _count(session: AsyncSession, model: type) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


async def _assert_no_payment_records(session: AsyncSession) -> None:
    assert await _count(session, Transaction) == 0
    assert await _count(session, TransactionSplit) == 0
    assert await _count(session, Debt) == 0


@pytest.mark.asyncio
async def test_split_failure_rolls_back_payment_and_previous_split(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dto = await _setup_payment(session)
    service = TransactionService(session)
    original_add_split = service._tx_repo.add_split
    calls = 0

    async def fail_on_second_split(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced split failure")
        return await original_add_split(**kwargs)

    monkeypatch.setattr(service._tx_repo, "add_split", fail_on_second_split)

    with pytest.raises(RuntimeError, match="forced split failure"):
        await service.create_one_time(dto)

    await _assert_no_payment_records(session)


@pytest.mark.asyncio
async def test_debt_failure_rolls_back_payment_splits_and_previous_debt(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dto = await _setup_payment(session)
    service = TransactionService(session)
    original_create_debt = service._debt_repo.create
    calls = 0

    async def fail_on_second_debt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced debt failure")
        return await original_create_debt(**kwargs)

    monkeypatch.setattr(service._debt_repo, "create", fail_on_second_debt)

    with pytest.raises(RuntimeError, match="forced debt failure"):
        await service.create_one_time(dto)

    await _assert_no_payment_records(session)


@pytest.mark.asyncio
async def test_final_load_failure_rolls_back_complete_payment(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dto = await _setup_payment(session)
    service = TransactionService(session)

    async def fail_final_load(transaction_id: int, user_id: int):
        raise RuntimeError("forced final load failure")

    monkeypatch.setattr(service._tx_repo, "get_for_user", fail_final_load)

    with pytest.raises(RuntimeError, match="forced final load failure"):
        await service.create_one_time(dto)

    await _assert_no_payment_records(session)


@pytest.mark.asyncio
async def test_one_time_payment_can_retry_after_atomic_rollback(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dto = await _setup_payment(session)
    service = TransactionService(session)
    original_create_debt = service._debt_repo.create

    async def fail_debt(**kwargs):
        raise RuntimeError("forced debt failure")

    monkeypatch.setattr(service._debt_repo, "create", fail_debt)
    with pytest.raises(RuntimeError, match="forced debt failure"):
        await service.create_one_time(dto)

    await _assert_no_payment_records(session)
    monkeypatch.setattr(service._debt_repo, "create", original_create_debt)

    tx = await service.create_one_time(dto)

    assert tx.id is not None
    assert await _count(session, Transaction) == 1
    assert await _count(session, TransactionSplit) == 3
    assert await _count(session, Debt) == 2
