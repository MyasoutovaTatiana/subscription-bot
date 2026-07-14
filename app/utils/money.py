"""Money helpers based on Decimal."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0")


class MoneyError(ValueError):
    """Invalid monetary amount."""


def parse_amount(raw: str) -> Decimal:
    """
    Parse user-entered amount.

    Accepts ``20``, ``20.5``, ``20,50``, ``1 850,40``.
    Rejects zero and negative values.
    """
    normalized = raw.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not normalized:
        raise MoneyError("Укажи сумму числом, например 20 или 399,90")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise MoneyError("Не получилось распознать сумму. Пример: 20 или 399,90") from exc
    if amount <= ZERO:
        raise MoneyError("Сумма должна быть больше нуля")
    return amount


def quantize_money(amount: Decimal) -> Decimal:
    """Round to kopecks (2 decimal places)."""
    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def format_number(amount: Decimal, *, decimals: int | None = None) -> str:
    """
    Format number for Russian UI: space thousands, comma decimals.

    If ``decimals`` is set, keep exactly that many fractional digits
    (trailing zeros preserved). Otherwise strip trailing zeros.
    """
    if decimals is not None:
        q = Decimal(1).scaleb(-decimals)
        amount = amount.quantize(q, rounding=ROUND_HALF_UP)

    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    text = format(amount, "f")
    if "." in text:
        whole, frac = text.split(".", 1)
        if decimals is None:
            frac = frac.rstrip("0")
        else:
            frac = frac.ljust(decimals, "0")[:decimals]
    else:
        whole, frac = text, ""
        if decimals is not None:
            frac = "0" * decimals

    # thousands separator
    whole_fmt = ""
    for i, ch in enumerate(reversed(whole)):
        if i and i % 3 == 0:
            whole_fmt = " " + whole_fmt
        whole_fmt = ch + whole_fmt

    if frac:
        return f"{sign}{whole_fmt},{frac}"
    return f"{sign}{whole_fmt}"


def format_money(amount: Decimal, currency: str) -> str:
    """Format amount with currency symbol/code (always 2 decimal places for money)."""
    from app.models.enums import CURRENCY_SYMBOLS, CurrencyCode

    code = currency.upper()
    formatted = format_number(amount, decimals=2)
    # strip ",00"
    if formatted.endswith(",00"):
        formatted = formatted[:-3]
    try:
        symbol = CURRENCY_SYMBOLS[CurrencyCode(code)]
    except ValueError:
        return f"{formatted} {code}"

    if code == CurrencyCode.RUB:
        return f"{formatted} {symbol}"
    if code in {CurrencyCode.USD, CurrencyCode.EUR}:
        return f"{symbol}{formatted}"
    return f"{formatted} {symbol}"
