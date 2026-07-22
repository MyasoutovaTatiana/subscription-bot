"""Next charge date calculation."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.models.enums import BillingType


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping day to last day of target month."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def add_years_preserving_leap_day(d: date, years: int = 1) -> date:
    """
    Add years. Feb 29 rolls to Feb 28 in non-leap years.
    """
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def next_monthly_date(from_date: date, billing_day: int) -> date:
    """
    Next occurrence of ``billing_day`` strictly after ``from_date``
    is not required — this advances one month from current charge date,
    clamping day (31 in short months -> last day).
    """
    if not (1 <= billing_day <= 31):
        raise ValueError("billing_day must be 1..31")
    # Calculate the target month first, then clamp the original billing-day anchor.
    # Clamping the current month before adding a month would make a subscription on
    # the 31st stick to the 28th after February instead of returning to the 31st.
    target_month = from_date.month
    target_year = from_date.year
    if target_month == 12:
        target_month = 1
        target_year += 1
    else:
        target_month += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, min(billing_day, last_day))


def calculate_next_charge_date(
    *,
    billing_type: BillingType | str,
    current_charge_date: date,
    billing_day: int | None = None,
    billing_interval: int | None = None,
) -> date | None:
    """
    Compute the next charge date after a confirmed charge on ``current_charge_date``.

    Returns None for BillingType.NONE (no automatic recurrence).
    """
    btype = BillingType(billing_type)

    if btype == BillingType.NONE:
        return None

    if btype == BillingType.MONTHLY:
        day = billing_day or current_charge_date.day
        return next_monthly_date(current_charge_date, day)

    if btype in {BillingType.EVERY_N_DAYS, BillingType.CUSTOM}:
        if billing_interval is None or billing_interval < 1:
            raise ValueError("billing_interval must be >= 1 for interval billing")
        return current_charge_date + timedelta(days=billing_interval)

    if btype == BillingType.YEARLY:
        return add_years_preserving_leap_day(current_charge_date, 1)

    raise ValueError(f"Unsupported billing type: {billing_type}")


def billing_label(
    billing_type: BillingType | str,
    *,
    billing_interval: int | None = None,
    billing_day: int | None = None,
) -> str:
    btype = BillingType(billing_type)
    if btype == BillingType.MONTHLY:
        if billing_day:
            return f"каждый месяц {billing_day}-го числа"
        return "каждый месяц"
    if btype == BillingType.EVERY_N_DAYS:
        n = billing_interval or 0
        return f"каждые {n} дн."
    if btype == BillingType.CUSTOM:
        n = billing_interval or 0
        return f"каждые {n} дн. (свой интервал)"
    if btype == BillingType.YEARLY:
        return "каждый год"
    return "без автоматического повторения"


def billing_label_short(
    billing_type: BillingType | str,
    *,
    billing_interval: int | None = None,
) -> str:
    """Compact label for cards (sentence case for body under emoji header)."""
    btype = BillingType(billing_type)
    if btype == BillingType.MONTHLY:
        return "Каждый месяц"
    if btype == BillingType.EVERY_N_DAYS:
        n = billing_interval or 0
        return f"Каждые {n} дн."
    if btype == BillingType.CUSTOM:
        n = billing_interval or 0
        return f"Каждые {n} дн."
    if btype == BillingType.YEARLY:
        return "Каждый год"
    return "Без повторения"
