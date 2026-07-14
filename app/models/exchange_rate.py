"""Cached exchange rates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExchangeRate(Base, TimestampMixin):
    """Official (or cached) FX rate into RUB for a currency on a date."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("currency", "rate_date", "source", name="uq_exchange_rates_currency_date_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nominal: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    value_rub: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unit_rate_rub: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cbr")

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.currency} {self.rate_date}={self.unit_rate_rub}>"
