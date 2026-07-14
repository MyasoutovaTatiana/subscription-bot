"""Currency conversion service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CurrencyCode
from app.repositories.exchange_rates import ExchangeRateRepository
from app.services.exchange_rates.base import ExchangeRateProvider, RateQuote
from app.services.exchange_rates.cbr import CbrExchangeRateProvider
from app.utils.money import quantize_money

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConversionResult:
    original_amount: Decimal
    currency: str
    rub_amount: Decimal
    unit_rate_rub: Decimal
    rate_date: date
    nominal: int
    source: str
    from_cache_fallback: bool = False


class CurrencyConverter:
    """
    Convert amounts to RUB using ExchangeRateProvider + DB cache.

    Never uses future rates. Falls back to last cached rate if provider fails.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: ExchangeRateProvider | None = None,
    ) -> None:
        self._session = session
        self._repo = ExchangeRateRepository(session)
        self._provider = provider or CbrExchangeRateProvider()

    async def convert_to_rub(
        self,
        amount: Decimal,
        currency: str,
        on_date: date,
    ) -> ConversionResult:
        code = currency.upper()
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")

        if code == CurrencyCode.RUB.value:
            return ConversionResult(
                original_amount=amount,
                currency=code,
                rub_amount=quantize_money(amount),
                unit_rate_rub=Decimal("1"),
                rate_date=on_date,
                nominal=1,
                source="identity",
            )

        rate = await self._repo.get_latest_on_or_before(code, on_date)
        fetched = False
        if rate is None or rate.rate_date != on_date:
            # Try refresh from provider for on_date (provider itself walks back weekends).
            try:
                quotes = await self._provider.fetch_rates(on_date)
                if quotes:
                    await self._repo.upsert_many(quotes)
                    fetched = True
                    rate = await self._repo.get_latest_on_or_before(code, on_date)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to refresh FX rates for %s", on_date)

        if rate is None:
            raise LookupError(
                "Сейчас не удалось узнать курс. "
                "Попробуй позже или укажи сумму в рублях вручную."
            )

        from_cache_fallback = not fetched and rate.rate_date != on_date
        rub = quantize_money(amount * Decimal(rate.unit_rate_rub))
        return ConversionResult(
            original_amount=amount,
            currency=code,
            rub_amount=rub,
            unit_rate_rub=Decimal(rate.unit_rate_rub),
            rate_date=rate.rate_date,
            nominal=rate.nominal,
            source=rate.source,
            from_cache_fallback=from_cache_fallback or rate.rate_date != on_date,
        )

    async def ensure_cached(self, on_date: date) -> list[RateQuote]:
        quotes = await self._provider.fetch_rates(on_date)
        if quotes:
            await self._repo.upsert_many(quotes)
        return quotes
