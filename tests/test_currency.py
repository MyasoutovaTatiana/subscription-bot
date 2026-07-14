"""Currency conversion tests (no live network)."""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.services.currency import CurrencyConverter
from app.services.exchange_rates.base import ExchangeRateProvider, RateQuote


class FakeProvider(ExchangeRateProvider):
    def __init__(self, quotes: list[RateQuote] | None = None, fail: bool = False) -> None:
        self.quotes = quotes or []
        self.fail = fail
        self.calls = 0

    async def fetch_rates(self, on_date: date) -> list[RateQuote]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("network down")
        # only return quotes not after on_date
        return [q for q in self.quotes if q.rate_date <= on_date]


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
async def test_usd_to_rub(session: AsyncSession) -> None:
    provider = FakeProvider(
        [
            RateQuote(
                currency="USD",
                rate_date=date(2026, 7, 18),
                nominal=1,
                value_rub=Decimal("92.50"),
                unit_rate_rub=Decimal("92.50"),
            )
        ]
    )
    converter = CurrencyConverter(session, provider=provider)
    result = await converter.convert_to_rub(Decimal("20"), "USD", date(2026, 7, 18))
    assert result.rub_amount == Decimal("1850.00")
    assert result.unit_rate_rub == Decimal("92.50")


@pytest.mark.asyncio
async def test_currency_with_nominal(session: AsyncSession) -> None:
    # e.g. VND or JPY-like: 10000 units = 35.5 RUB => unit = 0.00355
    provider = FakeProvider(
        [
            RateQuote(
                currency="VND",
                rate_date=date(2026, 7, 18),
                nominal=10000,
                value_rub=Decimal("35.50"),
                unit_rate_rub=Decimal("0.00355"),
            )
        ]
    )
    converter = CurrencyConverter(session, provider=provider)
    result = await converter.convert_to_rub(Decimal("10000"), "VND", date(2026, 7, 18))
    assert result.rub_amount == Decimal("35.50")


@pytest.mark.asyncio
async def test_rub_identity(session: AsyncSession) -> None:
    converter = CurrencyConverter(session, provider=FakeProvider([]))
    result = await converter.convert_to_rub(Decimal("100.555"), "RUB", date(2026, 7, 18))
    assert result.rub_amount == Decimal("100.56")
    assert result.unit_rate_rub == Decimal("1")


@pytest.mark.asyncio
async def test_fallback_to_last_cached_rate(session: AsyncSession) -> None:
    provider = FakeProvider(
        [
            RateQuote(
                currency="USD",
                rate_date=date(2026, 7, 17),
                nominal=1,
                value_rub=Decimal("90"),
                unit_rate_rub=Decimal("90"),
            )
        ],
    )
    converter = CurrencyConverter(session, provider=provider)
    # First call caches Friday rate
    await converter.convert_to_rub(Decimal("1"), "USD", date(2026, 7, 17))
    # Provider fails on weekend request — still use cached
    provider.fail = True
    provider.quotes = []
    result = await converter.convert_to_rub(Decimal("10"), "USD", date(2026, 7, 18))
    assert result.rub_amount == Decimal("900.00")
    assert result.rate_date == date(2026, 7, 17)
    assert result.from_cache_fallback is True


@pytest.mark.asyncio
async def test_no_future_rate(session: AsyncSession) -> None:
    provider = FakeProvider(
        [
            RateQuote(
                currency="USD",
                rate_date=date(2026, 7, 20),
                nominal=1,
                value_rub=Decimal("100"),
                unit_rate_rub=Decimal("100"),
            )
        ]
    )
    converter = CurrencyConverter(session, provider=provider)
    with pytest.raises(LookupError):
        await converter.convert_to_rub(Decimal("1"), "USD", date(2026, 7, 18))
