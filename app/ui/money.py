"""
UI Kit — money & currency display.

Все суммы в сообщениях бота форматируются только через эти функции.
Расчёты остаются в ``app.utils.money`` / services.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.enums import CurrencyCode
from app.ui.tokens import Copy
from app.utils.money import format_money as _format_money
from app.utils.money import format_number as _format_number


def money(amount: Decimal | str | int | float, currency: str) -> str:
    """Primary amount: ``$20``, ``1 850,40 ₽``, ``€12,50``."""
    return _format_money(Decimal(str(amount)), currency)


def number(amount: Decimal | str | int | float, *, decimals: int | None = None) -> str:
    """Bare number for rates etc.: ``92,50``."""
    return _format_number(Decimal(str(amount)), decimals=decimals)


def money_with_estimate(
    amount: Decimal,
    currency: str,
    *,
    estimated_rub: Decimal | None = None,
) -> str:
    """
    Cost block body:

        $20,40
        ≈ 1 860 ₽
    """
    primary = money(amount, currency)
    estimate = rub_estimate(estimated_rub, currency=currency)
    if not estimate:
        return primary
    return f"{primary}\n{estimate}"


def rub_estimate(estimated_rub: Decimal | None, *, currency: str) -> str:
    """Secondary RUB line — never mentions Банк России / ЦБ / tech setup."""
    if currency.upper() == CurrencyCode.RUB.value:
        return ""
    if estimated_rub is not None:
        return f"≈ {money(estimated_rub, CurrencyCode.RUB.value)}"
    return Copy.RATE_PENDING


def rate_line(label: str, rate: Decimal, currency: str) -> str:
    """Human rate: ``1 USD = 76,62 ₽`` under a label (max 2 decimals)."""
    return f"{label}\n1 {currency.upper()} = {number(rate, decimals=2)} ₽"
