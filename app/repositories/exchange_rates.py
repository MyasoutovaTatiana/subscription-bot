"""Exchange rate repository."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange_rate import ExchangeRate
from app.services.exchange_rates.base import RateQuote


class ExchangeRateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_quote(self, quote: RateQuote) -> ExchangeRate:
        existing = await self.get_exact(quote.currency, quote.rate_date, quote.source)
        if existing:
            existing.nominal = quote.nominal
            existing.value_rub = quote.value_rub
            existing.unit_rate_rub = quote.unit_rate_rub
            await self._session.flush()
            return existing
        row = ExchangeRate(
            currency=quote.currency.upper(),
            rate_date=quote.rate_date,
            nominal=quote.nominal,
            value_rub=quote.value_rub,
            unit_rate_rub=quote.unit_rate_rub,
            source=quote.source,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_exact(self, currency: str, rate_date: date, source: str = "cbr") -> ExchangeRate | None:
        result = await self._session.execute(
            select(ExchangeRate).where(
                ExchangeRate.currency == currency.upper(),
                ExchangeRate.rate_date == rate_date,
                ExchangeRate.source == source,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_on_or_before(
        self,
        currency: str,
        on_date: date,
        *,
        source: str = "cbr",
    ) -> ExchangeRate | None:
        """Last stored official rate with rate_date <= on_date (never from the future)."""
        result = await self._session.execute(
            select(ExchangeRate)
            .where(
                ExchangeRate.currency == currency.upper(),
                ExchangeRate.rate_date <= on_date,
                ExchangeRate.source == source,
            )
            .order_by(ExchangeRate.rate_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_many(self, quotes: list[RateQuote]) -> None:
        for quote in quotes:
            await self.upsert_quote(quote)
