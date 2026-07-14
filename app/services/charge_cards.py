"""Render saved charge (transaction) cards via UI Kit."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.enums import CurrencyCode
from app.models.transaction import Transaction
from app.ui import (
    Copy,
    Icon,
    entity_name,
    field,
    money,
    number,
    screen,
    success_screen,
    success_title,
    title,
)
from app.utils.dates import format_charge_when, format_date_ru, format_date_ru_short


def format_charge_confirmed(*, next_charge_date: date | None) -> str:
    """Simple success after confirming a subscription charge."""
    if next_charge_date is not None:
        next_body = f"{format_date_ru_short(next_charge_date)}."
    else:
        next_body = "Без повторения"
    return success_screen(
        Copy.CHARGE_CONFIRMED,
        field(Icon.CALENDAR, Copy.NEXT_CHARGE_LABEL, next_body),
    )


def format_charge_card(
    tx: Transaction,
    *,
    next_charge_date: date | None = None,
    heading: str | None = None,
) -> str:
    """
    Full charge card after save / on reopen.

    Shows original amount, estimate, fact, charge date, next charge.
    """
    head = heading or success_title(Copy.CHARGE_SAVED)
    if heading and not heading.startswith(("✅", "❌", "ℹ️", "⚠️")) and "<b>" not in heading:
        head = title(Icon.PAYMENT, heading)

    original = money(Decimal(tx.original_amount), tx.original_currency)
    estimated = money(Decimal(tx.estimated_rub_amount), CurrencyCode.RUB.value)
    if tx.original_currency == CurrencyCode.RUB.value:
        estimate_body = estimated
    else:
        estimate_body = f"≈ {estimated}"

    if tx.actual_rub_amount is not None:
        actual_body = money(Decimal(tx.actual_rub_amount), CurrencyCode.RUB.value)
    else:
        actual_body = Copy.NOT_SET

    charge_when = format_date_ru(tx.transaction_date)
    if next_charge_date is not None:
        next_body = format_charge_when(next_charge_date)
    else:
        next_body = "Без повторения"

    return screen(
        head,
        entity_name(Icon.SUBSCRIPTION, tx.name),
        field(Icon.MONEY, Copy.ORIGINAL_AMOUNT_LABEL, original),
        field(Icon.RATE, Copy.ESTIMATED_RUB_LABEL, estimate_body),
        field(Icon.CHECK, Copy.ACTUAL_RUB_LABEL, actual_body),
        field(Icon.CALENDAR, Copy.CHARGE_DATE_LABEL, charge_when),
        field(Icon.CALENDAR, Copy.NEXT_CHARGE_LABEL, next_body),
    )


def format_amount_updated(
    *,
    was: Decimal,
    now: Decimal,
) -> str:
    return success_screen(
        Copy.AMOUNT_UPDATED,
        f"Было: {money(was, CurrencyCode.RUB.value)}",
        f"Стало: {money(now, CurrencyCode.RUB.value)}",
        footer=Copy.DEBTS_RECALCULATED,
    )


def format_rate_updated(*, estimated_rub: Decimal, rate: Decimal, currency: str) -> str:
    return success_screen(
        Copy.RATE_UPDATED,
        field(Icon.RATE, "Курс", f"{number(rate)} ₽ / 1 {currency}"),
        field(
            Icon.MONEY,
            Copy.ESTIMATED_RUB_LABEL,
            f"≈ {money(estimated_rub, CurrencyCode.RUB.value)}",
        ),
    )
