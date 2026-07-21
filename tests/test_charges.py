"""ChargeService: RUB vs foreign currency behaviour for confirm flow."""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.enums import BillingType, CurrencyCode, SubscriptionCategory
from app.models.exchange_rate import ExchangeRate
from app.services.charges import ChargeService
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
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


async def _seed_rate(session: AsyncSession, currency: str, unit: Decimal) -> None:
    session.add(
        ExchangeRate(
            currency=currency,
            rate_date=date(2026, 7, 14),
            nominal=1,
            value_rub=unit,
            unit_rate_rub=unit,
            source="cbr",
        )
    )
    await session.flush()


async def _user(session: AsyncSession):
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=7,
        telegram_chat_id=7,
        username="t",
        first_name="T",
    )
    return user


async def _sub(session: AsyncSession, user_id: int, *, amount: Decimal, currency: str):
    return await SubscriptionService(session).create(
        CreateSubscriptionDTO(
            user_id=user_id,
            name="Test Sub",
            category=SubscriptionCategory.AI_WORK.value,
            amount=amount,
            currency=currency,
            billing_type=BillingType.MONTHLY.value,
            billing_interval=None,
            billing_day=14,
            next_charge_date=date(2026, 7, 14),
            payment_method_id=None,
            reminder_offsets=[0],
            reminder_time="10:00",
        )
    )


@pytest.mark.asyncio
async def test_confirm_rub_with_actual(session: AsyncSession) -> None:
    user = await _user(session)
    sub = await _sub(session, user.id, amount=Decimal("399"), currency="RUB")
    tx, next_date, estimated, actual = await ChargeService(session).confirm_charged(
        sub,
        user_id=user.id,
        actual_rub_amount=Decimal("399"),
    )
    await session.commit()
    assert estimated == Decimal("399.00")
    assert actual == Decimal("399.00")
    assert tx.actual_rub_amount == Decimal("399.00")
    assert next_date == date(2026, 8, 14)


@pytest.mark.asyncio
async def test_confirm_usd_with_actual_rub(session: AsyncSession) -> None:
    user = await _user(session)
    await _seed_rate(session, "USD", Decimal("90"))
    sub = await _sub(session, user.id, amount=Decimal("20.40"), currency="USD")
    tx, _next, estimated, actual = await ChargeService(session).confirm_charged(
        sub,
        user_id=user.id,
        actual_rub_amount=Decimal("1850.50"),
    )
    await session.commit()
    assert estimated == Decimal("1836.00")  # 20.40 * 90
    assert actual == Decimal("1850.50")
    assert tx.conversion_mode == "actual_rub"
    assert tx.is_rate_estimated is False


@pytest.mark.asyncio
async def test_confirm_usd_skip_keeps_estimate(session: AsyncSession) -> None:
    user = await _user(session)
    await _seed_rate(session, "USD", Decimal("90"))
    sub = await _sub(session, user.id, amount=Decimal("10"), currency="USD")
    tx, _next, estimated, actual = await ChargeService(session).confirm_charged(
        sub,
        user_id=user.id,
    )
    await session.commit()
    assert estimated == Decimal("900.00")
    assert actual is None
    assert tx.is_rate_estimated is True
    assert tx.conversion_mode == "cbr"


@pytest.mark.asyncio
async def test_confirm_eur_and_cny(session: AsyncSession) -> None:
    user = await _user(session)
    await _seed_rate(session, "EUR", Decimal("100"))
    await _seed_rate(session, "CNY", Decimal("12.50"))

    eur_sub = await _sub(session, user.id, amount=Decimal("9.99"), currency="EUR")
    _tx, _n, est_eur, _a = await ChargeService(session).confirm_charged(
        eur_sub,
        user_id=user.id,
    )
    assert est_eur == Decimal("999.00")

    cny_sub = await _sub(session, user.id, amount=Decimal("68"), currency="CNY")
    _tx2, _n2, est_cny, _a2 = await ChargeService(session).confirm_charged(
        cny_sub,
        user_id=user.id,
    )
    assert est_cny == Decimal("850.00")


@pytest.mark.asyncio
async def test_update_actual_and_undo(session: AsyncSession) -> None:
    from app.models.friend import Friend
    from app.repositories.subscriptions import SubscriptionRepository

    user = await _user(session)
    await _seed_rate(session, "USD", Decimal("90"))
    friend = Friend(user_id=user.id, name="Аня")
    session.add(friend)
    await session.flush()

    sub = await _sub(session, user.id, amount=Decimal("20"), currency="USD")
    sub_id = sub.id
    user_id = user.id
    await SubscriptionRepository(session).add_participant(
        subscription_id=sub_id,
        friend_id=friend.id,
    )
    await session.commit()
    session.expire_all()
    sub = await SubscriptionService(session).get(sub_id, user_id)
    assert sub is not None
    assert len(sub.participants) == 1

    service = ChargeService(session)
    tx, next_date, _est, _act = await service.confirm_charged(
        sub,
        user_id=user_id,
        actual_rub_amount=Decimal("1800"),
    )
    assert next_date == date(2026, 8, 14)

    tx = await service.get_for_user(tx.id, user_id)
    assert tx is not None
    assert len([d for d in tx.debts if d.status == "active"]) == 1
    assert tx.debts[0].amount_rub == Decimal("900.00")  # equal split with owner

    was, now = await service.update_actual_rub(tx, Decimal("2000"))
    assert was == Decimal("1800.00")
    assert now == Decimal("2000.00")
    tx = await service.get_for_user(tx.id, user_id)
    assert tx is not None
    assert tx.debts[0].amount_rub == Decimal("1000.00")

    estimated = await service.update_rate(tx, Decimal("95"))
    assert estimated == Decimal("1900.00")
    # fact set — debts stay on actual
    tx = await service.get_for_user(tx.id, user_id)
    assert tx is not None
    assert tx.actual_rub_amount == Decimal("2000.00")

    await service.update_charge_date(tx, date(2026, 7, 20))
    sub = await SubscriptionService(session).get(sub_id, user_id)
    assert sub is not None
    assert sub.next_charge_date == date(2026, 8, 20)

    tx = await service.get_for_user(tx.id, user_id)
    assert tx is not None
    restored = await service.undo_charge(tx)
    assert restored is not None
    assert restored.next_charge_date == date(2026, 7, 20)
    assert await service.get_for_user(tx.id, user_id) is None


@pytest.mark.asyncio
async def test_delete_keeps_next_date(session: AsyncSession) -> None:
    user = await _user(session)
    await _seed_rate(session, "USD", Decimal("90"))
    sub = await _sub(session, user.id, amount=Decimal("10"), currency="USD")
    service = ChargeService(session)
    tx, next_date, _e, _a = await service.confirm_charged(
        sub,
        user_id=user.id,
    )
    assert next_date == date(2026, 8, 14)
    tx = await service.get_for_user(tx.id, user.id)
    assert tx is not None
    sub2 = await service.delete_charge(tx)
    assert sub2 is not None
    assert sub2.next_charge_date == date(2026, 8, 14)
