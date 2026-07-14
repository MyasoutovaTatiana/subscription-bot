"""Exchange rate provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RateQuote:
    currency: str
    rate_date: date
    nominal: int
    value_rub: Decimal
    unit_rate_rub: Decimal
    source: str = "cbr"


class ExchangeRateProvider(ABC):
    """Fetches official FX rates into RUB."""

    @abstractmethod
    async def fetch_rates(self, on_date: date) -> list[RateQuote]:
        """Return quotes available for ``on_date`` (or empty if unavailable)."""
