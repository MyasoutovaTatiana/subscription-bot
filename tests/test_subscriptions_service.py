"""Async tests for subscription service."""

import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.enums import BillingType, SubscriptionCategory
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


@pytest.mark.asyncio
async def test_create_subscription(session: AsyncSession) -> None:
    user, _ = await UserService(session).get_or_create_from_telegram(
        telegram_user_id=42,
        telegram_chat_id=42,
        username="u",
        first_name="U",
    )
    service = SubscriptionService(session)
    sub = await service.create(
        CreateSubscriptionDTO(
            user_id=user.id,
            name="ChatGPT Plus",
            category=SubscriptionCategory.AI_WORK.value,
            amount=Decimal("20"),
            currency="USD",
            billing_type=BillingType.MONTHLY.value,
            billing_interval=None,
            billing_day=20,
            next_charge_date=date(2026, 7, 20),
            payment_method_id=None,
            reminder_offsets=[3, 1, 0],
            reminder_time="10:00",
        )
    )
    await session.commit()
    assert sub.id is not None
    assert sub.name == "ChatGPT Plus"
    loaded = await service.get(sub.id, user.id)
    assert loaded is not None
    assert loaded.amount == Decimal("20")
