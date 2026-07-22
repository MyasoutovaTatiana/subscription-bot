"""Security regression tests for debt deep-link claiming."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.handlers.debts import show_friend_debt
from app.models import Base
from app.models.debt import Debt
from app.models.enums import DebtStatus, TransactionType
from app.models.friend import Friend
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.debts import DebtRepository


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _make_debt(
    session: AsyncSession,
    *,
    status: str = DebtStatus.ACTIVE.value,
    payer_telegram_id: int | None = None,
) -> Debt:
    owner = User(
        telegram_user_id=1001,
        telegram_chat_id=1001,
        username="owner",
        first_name="Owner",
    )
    session.add(owner)
    await session.flush()
    friend = Friend(user_id=owner.id, name="Катя")
    session.add(friend)
    await session.flush()
    transaction = Transaction(
        user_id=owner.id,
        transaction_type=TransactionType.ONE_TIME.value,
        name="Секретный ужин",
        original_amount=Decimal("1000"),
        original_currency="RUB",
        estimated_rub_amount=Decimal("1000"),
        is_rate_estimated=False,
        transaction_date=date(2026, 7, 22),
    )
    session.add(transaction)
    await session.flush()
    debt = await DebtRepository(session).create(
        user_id=owner.id,
        transaction_id=transaction.id,
        friend_id=friend.id,
        amount_rub=Decimal("500.00"),
        status=status,
        payer_telegram_id=payer_telegram_id,
    )
    await session.commit()
    loaded = await DebtRepository(session).get_by_id(debt.id)
    assert loaded is not None
    return loaded


def _message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    return message


def _answer_text(message: MagicMock) -> str:
    return str(message.answer.await_args.args[0])


def test_share_token_uses_cryptographic_random_bytes() -> None:
    with patch("app.repositories.debts.secrets.token_urlsafe", return_value="safe-token") as token:
        assert DebtRepository.new_share_token() == "safe-token"
    token.assert_called_once_with(12)


@pytest.mark.asyncio
async def test_invalid_token_discloses_no_debt_data(session: AsyncSession) -> None:
    debt = await _make_debt(session)
    message = _message()

    await show_friend_debt(message, session, token="invalid", telegram_user_id=2002)

    text = _answer_text(message)
    assert "Ссылка недействительна" in text
    assert debt.transaction.name not in text
    assert "500" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DebtStatus.PAID.value, DebtStatus.CANCELLED.value])
async def test_closed_link_does_not_bind_or_disclose_data(
    session: AsyncSession,
    status: str,
) -> None:
    debt = await _make_debt(session, status=status)
    transaction_name = debt.transaction.name
    message = _message()

    await show_friend_debt(
        message,
        session,
        token=str(debt.share_token),
        telegram_user_id=2002,
    )

    await session.refresh(debt)
    text = _answer_text(message)
    assert debt.payer_telegram_id is None
    assert transaction_name not in text
    assert "500" not in text


@pytest.mark.asyncio
async def test_first_user_claims_link_and_other_user_cannot_overwrite_or_read(
    session: AsyncSession,
) -> None:
    debt = await _make_debt(session)
    transaction_name = debt.transaction.name
    first_message = _message()
    other_message = _message()

    await show_friend_debt(
        first_message,
        session,
        token=str(debt.share_token),
        telegram_user_id=2002,
    )
    await show_friend_debt(
        other_message,
        session,
        token=str(debt.share_token),
        telegram_user_id=3003,
    )

    await session.refresh(debt)
    assert debt.payer_telegram_id == 2002
    assert transaction_name in _answer_text(first_message)
    other_text = _answer_text(other_message)
    assert "другим человеком" in other_text
    assert transaction_name not in other_text
    assert "500" not in other_text


@pytest.mark.asyncio
async def test_same_user_can_reopen_claimed_link(session: AsyncSession) -> None:
    debt = await _make_debt(session, payer_telegram_id=2002)
    message = _message()

    await show_friend_debt(
        message,
        session,
        token=str(debt.share_token),
        telegram_user_id=2002,
    )

    assert debt.transaction.name in _answer_text(message)


@pytest.mark.asyncio
async def test_stale_competing_session_cannot_overwrite_first_claim(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deep-link.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as setup_session:
        debt = await _make_debt(setup_session)
        debt_id = debt.id
        token = str(debt.share_token)

    async with factory() as first_session, factory() as stale_session:
        stale_debt = await DebtRepository(stale_session).get_by_share_token(token)
        assert stale_debt is not None
        assert stale_debt.payer_telegram_id is None

        first_claim = await DebtRepository(first_session).claim_share_token(token, 2002)
        await first_session.commit()
        stale_claim = await DebtRepository(stale_session).claim_share_token(token, 3003)
        await stale_session.commit()

    async with factory() as verify_session:
        refreshed = await DebtRepository(verify_session).get_by_id(debt_id)
        assert refreshed is not None
        assert first_claim is True
        assert stale_claim is False
        assert refreshed.payer_telegram_id == 2002

    await engine.dispose()
