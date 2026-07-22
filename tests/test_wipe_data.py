"""Privacy P1 tests: wipe_data fully removes the user and everything they own.

Uses a temporary SQLite database with the real ORM models. Only the Telegram
Message / FSMContext are mocked (for the handler-level tests).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.engine import create_engine
from app.handlers.settings import wipe_data
from app.models import Base
from app.models.debt import Debt
from app.models.enums import (
    BillingType,
    DebtStatus,
    ReminderStatus,
    SubscriptionCategory,
    TransactionType,
)
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit
from app.models.user import User
from app.repositories.users import UserRepository
from app.services.users import UserService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _count(session: AsyncSession, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return int((await session.execute(stmt)).scalar_one())


async def seed_full_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    username: str,
) -> User:
    """Create a user with one of every supported owned data type."""
    user = User(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_user_id,
        username=username,
        first_name=username.capitalize(),
    )
    session.add(user)
    await session.flush()

    friend = Friend(user_id=user.id, name=f"{username}-friend")
    method = PaymentMethod(user_id=user.id, name=f"{username}-card")
    session.add_all([friend, method])
    await session.flush()

    subscription = Subscription(
        user_id=user.id,
        name=f"{username}-netflix",
        category=SubscriptionCategory.VIDEO_MUSIC.value,
        amount=Decimal("10.00"),
        currency="USD",
        billing_type=BillingType.MONTHLY.value,
        next_charge_date=date(2026, 8, 1),
        reminder_offsets=[3, 1, 0],
    )
    session.add(subscription)
    await session.flush()

    participant = SubscriptionParticipant(
        subscription_id=subscription.id,
        friend_id=friend.id,
        share_value=Decimal("0.5"),
    )
    session.add(participant)

    transaction = Transaction(
        user_id=user.id,
        subscription_id=subscription.id,
        transaction_type=TransactionType.ONE_TIME.value,
        name=f"{username}-dinner",
        original_amount=Decimal("1000"),
        original_currency="RUB",
        estimated_rub_amount=Decimal("1000"),
        is_rate_estimated=False,
        transaction_date=date(2026, 7, 14),
    )
    session.add(transaction)
    await session.flush()

    split = TransactionSplit(
        transaction_id=transaction.id,
        friend_id=friend.id,
        is_owner=False,
        amount_rub=Decimal("500.00"),
    )
    session.add(split)

    debt = Debt(
        user_id=user.id,
        transaction_id=transaction.id,
        friend_id=friend.id,
        amount_rub=Decimal("500.00"),
        status=DebtStatus.ACTIVE.value,
    )
    session.add(debt)

    reminder = ReminderDelivery(
        user_id=user.id,
        subscription_id=subscription.id,
        charge_date=date(2026, 8, 1),
        reminder_offset=1,
        scheduled_at=datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc),
        status=ReminderStatus.PENDING.value,
        unique_key=ReminderDelivery.build_unique_key(subscription.id, date(2026, 8, 1), 1),
    )
    session.add(reminder)
    await session.flush()
    return user


ALL_OWNED_MODELS = (
    Subscription,
    Transaction,
    Debt,
    PaymentMethod,
    Friend,
    ReminderDelivery,
)


@pytest.mark.asyncio
async def test_wipe_removes_user_and_all_owned_data(session: AsyncSession) -> None:
    user = await seed_full_user(session, telegram_user_id=1001, username="alice")
    await session.commit()
    user_id = user.id

    await UserService(session).wipe_user(user, user_id=user.id)
    await session.commit()

    assert await session.get(User, user_id) is None
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=user_id) == 0


@pytest.mark.asyncio
async def test_wipe_a_keeps_b_intact(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    await session.commit()
    bob_id = bob.id

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    assert await session.get(User, bob_id) is not None
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=bob_id) == 1


@pytest.mark.asyncio
async def test_wipe_clears_payer_telegram_id_on_other_user_debt(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")

    # Bob has a debt whose payer is Alice (direct Telegram binding).
    bob_debt = (
        await session.execute(select(Debt).where(Debt.user_id == bob.id))
    ).scalar_one()
    bob_debt.payer_telegram_id = alice.telegram_user_id
    original_amount = bob_debt.amount_rub
    original_status = bob_debt.status
    debt_id = bob_debt.id
    await session.commit()

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    refreshed = await session.get(Debt, debt_id)
    assert refreshed is not None
    assert refreshed.payer_telegram_id is None
    assert refreshed.amount_rub == original_amount
    assert refreshed.status == original_status


@pytest.mark.asyncio
async def test_wipe_leaves_no_orphans(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    await session.commit()

    alice_tx_ids = {
        row.id
        for row in (
            await session.execute(select(Transaction).where(Transaction.user_id == alice.id))
        ).scalars()
    }
    alice_sub_ids = {
        row.id
        for row in (
            await session.execute(select(Subscription).where(Subscription.user_id == alice.id))
        ).scalars()
    }
    assert alice_tx_ids
    assert alice_sub_ids

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    remaining_splits = (await session.execute(select(TransactionSplit))).scalars().all()
    remaining_participants = (
        await session.execute(select(SubscriptionParticipant))
    ).scalars().all()

    for split in remaining_splits:
        assert split.transaction_id not in alice_tx_ids
    for participant in remaining_participants:
        assert participant.subscription_id not in alice_sub_ids

    # Exactly Bob's single split + participant survive.
    assert len(remaining_splits) == 1
    assert len(remaining_participants) == 1

    for split in remaining_splits:
        assert await session.get(Transaction, split.transaction_id) is not None
    for participant in remaining_participants:
        assert await session.get(Subscription, participant.subscription_id) is not None


@pytest.mark.asyncio
async def test_get_or_create_after_wipe_creates_fresh_user(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    await session.commit()
    old_id = alice.id

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    service = UserService(session)
    new_user, created = await service.get_or_create_from_telegram(
        telegram_user_id=1001,
        telegram_chat_id=1001,
        username="alice",
        first_name="Alice",
    )
    await session.commit()

    assert created is True
    # A brand new row was created (the old one is gone); SQLite may recycle the
    # rowid once the table is empty, so identity is proven by created=True + defaults.
    assert await session.get(User, old_id) is not None  # the freshly created row
    assert new_user.timezone == "Europe/Moscow"
    assert new_user.default_reminder_time == "10:00"
    assert list(new_user.default_reminder_offsets) == [3, 1, 0]
    assert new_user.username == "alice"
    # No resurrected data.
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=new_user.id) == 0


@pytest.mark.asyncio
async def test_wipe_empty_user(session: AsyncSession) -> None:
    user = User(telegram_user_id=1001, telegram_chat_id=1001, username="empty")
    session.add(user)
    await session.commit()
    user_id = user.id

    await UserService(session).wipe_user(user, user_id=user.id)
    await session.commit()

    assert await session.get(User, user_id) is None


# --- Handler-level tests (Telegram Message / FSM are mocked) ---


def _message(text: str) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


def _state(data: dict) -> MagicMock:
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_handler_deletes_only_after_final_confirmation(session: AsyncSession) -> None:
    user = await seed_full_user(session, telegram_user_id=1001, username="alice")
    await session.commit()
    user_id = user.id

    message = _message("УДАЛИТЬ ВСЁ")
    state = _state({"wipe_step": 2})

    await wipe_data(message, state, session, user)

    assert await session.get(User, user_id) is None
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=user_id) == 0
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_first_step_does_not_delete(session: AsyncSession) -> None:
    user = await seed_full_user(session, telegram_user_id=1001, username="alice")
    await session.commit()
    user_id = user.id

    message = _message("УДАЛИТЬ")
    state = _state({"wipe_step": 1})

    await wipe_data(message, state, session, user)

    # Still present; only advanced to the second confirmation.
    assert await session.get(User, user_id) is not None
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=user_id) == 1
    state.update_data.assert_awaited_once_with(wipe_step=2)
    state.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_clears_fsm_on_success(session: AsyncSession) -> None:
    user = await seed_full_user(session, telegram_user_id=1001, username="alice")
    await session.commit()

    message = _message("УДАЛИТЬ ВСЁ")
    state = _state({"wipe_step": 2})

    await wipe_data(message, state, session, user)

    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_wipe_rolls_back_on_midway_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    await session.commit()
    alice_id = alice.id
    bob_id = bob.id

    original_execute = session.execute
    calls = {"n": 0}

    async def flaky_execute(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # fail partway through the ordered deletes
            raise RuntimeError("boom mid-wipe")
        return await original_execute(*args, **kwargs)

    monkeypatch.setattr(session, "execute", flaky_execute)

    with pytest.raises(RuntimeError):
        await UserRepository(session).wipe_user(alice, user_id=alice.id)

    monkeypatch.undo()
    await session.rollback()

    # All-or-nothing: nothing deleted for either user.
    assert await session.get(User, alice_id) is not None
    assert await session.get(User, bob_id) is not None
    for model in ALL_OWNED_MODELS:
        assert await _count(session, model, user_id=alice_id) == 1
        assert await _count(session, model, user_id=bob_id) == 1


# --- Legacy cross-user FK links (pre-owner-check, inserted directly) ---


async def _alice_friend_and_pm(session: AsyncSession, alice: User) -> tuple[Friend, PaymentMethod]:
    friend = (await session.execute(select(Friend).where(Friend.user_id == alice.id))).scalar_one()
    method = (
        await session.execute(select(PaymentMethod).where(PaymentMethod.user_id == alice.id))
    ).scalar_one()
    return friend, method


@pytest.mark.asyncio
async def test_wipe_nulls_legacy_payment_method_on_b(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    _, alice_pm = await _alice_friend_and_pm(session, alice)

    bob_sub = (
        await session.execute(select(Subscription).where(Subscription.user_id == bob.id))
    ).scalar_one()
    bob_tx = (
        await session.execute(select(Transaction).where(Transaction.user_id == bob.id))
    ).scalar_one()
    bob_sub.payment_method_id = alice_pm.id
    bob_tx.payment_method_id = alice_pm.id
    bob_sub_id, bob_tx_id = bob_sub.id, bob_tx.id
    alice_pm_id = alice_pm.id
    await session.commit()

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    refreshed_sub = await session.get(Subscription, bob_sub_id)
    refreshed_tx = await session.get(Transaction, bob_tx_id)
    assert refreshed_sub is not None
    assert refreshed_tx is not None
    assert refreshed_sub.payment_method_id is None
    assert refreshed_tx.payment_method_id is None
    assert await session.get(PaymentMethod, alice_pm_id) is None


@pytest.mark.asyncio
async def test_wipe_removes_legacy_participant_on_b_sub(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    alice_friend, _ = await _alice_friend_and_pm(session, alice)

    bob_sub = (
        await session.execute(select(Subscription).where(Subscription.user_id == bob.id))
    ).scalar_one()
    bob_sub_id = bob_sub.id
    # Extra participant pointing at Alice's friend (bypass owner-check).
    bad = SubscriptionParticipant(
        subscription_id=bob_sub.id,
        friend_id=alice_friend.id,
        share_value=Decimal("0.25"),
    )
    session.add(bad)
    await session.flush()
    bad_id = bad.id
    await session.commit()

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    assert await session.get(Subscription, bob_sub_id) is not None
    assert await session.get(SubscriptionParticipant, bad_id) is None
    # Bob's own legitimate participant (own friend) remains.
    remaining = (
        await session.execute(
            select(SubscriptionParticipant).where(
                SubscriptionParticipant.subscription_id == bob_sub_id
            )
        )
    ).scalars().all()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_wipe_legacy_friend_on_b_split_and_debt(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    alice_friend, _ = await _alice_friend_and_pm(session, alice)

    bob_tx = (
        await session.execute(select(Transaction).where(Transaction.user_id == bob.id))
    ).scalar_one()
    bob_tx_id = bob_tx.id

    # Point Bob's existing split at Alice's friend (bad split → deleted, not tombstoned).
    bob_split = (
        await session.execute(
            select(TransactionSplit).where(TransactionSplit.transaction_id == bob_tx.id)
        )
    ).scalar_one()
    bob_split.friend_id = alice_friend.id
    split_id = bob_split.id

    # Point Bob's existing debt at Alice's friend (NOT NULL → debt row deleted).
    bob_debt = (
        await session.execute(select(Debt).where(Debt.user_id == bob.id))
    ).scalar_one()
    bob_debt.friend_id = alice_friend.id
    debt_id = bob_debt.id
    await session.commit()

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    assert await session.get(Transaction, bob_tx_id) is not None
    assert await session.get(TransactionSplit, split_id) is None
    assert await session.get(Debt, debt_id) is None


@pytest.mark.asyncio
async def test_wipe_leaves_no_fk_to_deleted_friend_or_pm(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    alice_friend, alice_pm = await _alice_friend_and_pm(session, alice)
    alice_friend_id, alice_pm_id = alice_friend.id, alice_pm.id

    bob_sub = (
        await session.execute(select(Subscription).where(Subscription.user_id == bob.id))
    ).scalar_one()
    bob_tx = (
        await session.execute(select(Transaction).where(Transaction.user_id == bob.id))
    ).scalar_one()
    bob_sub.payment_method_id = alice_pm.id
    bob_tx.payment_method_id = alice_pm.id
    session.add(
        SubscriptionParticipant(
            subscription_id=bob_sub.id,
            friend_id=alice_friend.id,
            share_value=Decimal("0.1"),
        )
    )
    bob_split = (
        await session.execute(
            select(TransactionSplit).where(TransactionSplit.transaction_id == bob_tx.id)
        )
    ).scalar_one()
    bob_split.friend_id = alice_friend.id
    bob_debt = (
        await session.execute(select(Debt).where(Debt.user_id == bob.id))
    ).scalar_one()
    bob_debt.friend_id = alice_friend.id
    await session.commit()

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    assert await _count(session, Subscription, payment_method_id=alice_pm_id) == 0
    assert await _count(session, Transaction, payment_method_id=alice_pm_id) == 0
    assert await _count(session, SubscriptionParticipant, friend_id=alice_friend_id) == 0
    assert await _count(session, TransactionSplit, friend_id=alice_friend_id) == 0
    assert await _count(session, Debt, friend_id=alice_friend_id) == 0
    assert await session.get(Friend, alice_friend_id) is None
    assert await session.get(PaymentMethod, alice_pm_id) is None


@pytest.mark.asyncio
async def test_wipe_plain_b_without_cross_refs_unchanged(session: AsyncSession) -> None:
    alice = await seed_full_user(session, telegram_user_id=1001, username="alice")
    bob = await seed_full_user(session, telegram_user_id=2002, username="bob")
    await session.commit()
    bob_id = bob.id

    bob_sub = (
        await session.execute(select(Subscription).where(Subscription.user_id == bob.id))
    ).scalar_one()
    bob_tx = (
        await session.execute(select(Transaction).where(Transaction.user_id == bob.id))
    ).scalar_one()
    bob_friend = (
        await session.execute(select(Friend).where(Friend.user_id == bob.id))
    ).scalar_one()
    bob_pm = (
        await session.execute(select(PaymentMethod).where(PaymentMethod.user_id == bob.id))
    ).scalar_one()
    bob_debt = (
        await session.execute(select(Debt).where(Debt.user_id == bob.id))
    ).scalar_one()
    bob_split = (
        await session.execute(
            select(TransactionSplit).where(TransactionSplit.transaction_id == bob_tx.id)
        )
    ).scalar_one()
    bob_participant = (
        await session.execute(
            select(SubscriptionParticipant).where(
                SubscriptionParticipant.subscription_id == bob_sub.id
            )
        )
    ).scalar_one()

    snapshot = {
        "sub_id": bob_sub.id,
        "tx_id": bob_tx.id,
        "friend_id": bob_friend.id,
        "pm_id": bob_pm.id,
        "debt_id": bob_debt.id,
        "debt_amount": bob_debt.amount_rub,
        "debt_status": bob_debt.status,
        "debt_friend_id": bob_debt.friend_id,
        "split_id": bob_split.id,
        "split_friend_id": bob_split.friend_id,
        "participant_id": bob_participant.id,
        "participant_friend_id": bob_participant.friend_id,
        "sub_pm": bob_sub.payment_method_id,
        "tx_pm": bob_tx.payment_method_id,
    }

    await UserService(session).wipe_user(alice, user_id=alice.id)
    await session.commit()

    assert await session.get(User, bob_id) is not None
    assert await session.get(Subscription, snapshot["sub_id"]) is not None
    assert await session.get(Transaction, snapshot["tx_id"]) is not None
    assert await session.get(Friend, snapshot["friend_id"]) is not None
    assert await session.get(PaymentMethod, snapshot["pm_id"]) is not None
    debt = await session.get(Debt, snapshot["debt_id"])
    assert debt is not None
    assert debt.amount_rub == snapshot["debt_amount"]
    assert debt.status == snapshot["debt_status"]
    assert debt.friend_id == snapshot["debt_friend_id"]
    split = await session.get(TransactionSplit, snapshot["split_id"])
    assert split is not None
    assert split.friend_id == snapshot["split_friend_id"]
    participant = await session.get(SubscriptionParticipant, snapshot["participant_id"])
    assert participant is not None
    assert participant.friend_id == snapshot["participant_friend_id"]
    sub = await session.get(Subscription, snapshot["sub_id"])
    tx = await session.get(Transaction, snapshot["tx_id"])
    assert sub is not None and sub.payment_method_id == snapshot["sub_pm"]
    assert tx is not None and tx.payment_method_id == snapshot["tx_pm"]
