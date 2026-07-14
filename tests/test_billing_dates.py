"""Tests for billing date calculations."""

from datetime import date

from app.models.enums import BillingType
from app.services.billing_dates import calculate_next_charge_date


def test_monthly_next() -> None:
    nxt = calculate_next_charge_date(
        billing_type=BillingType.MONTHLY,
        current_charge_date=date(2026, 7, 20),
        billing_day=20,
    )
    assert nxt == date(2026, 8, 20)


def test_monthly_day_31_short_month() -> None:
    nxt = calculate_next_charge_date(
        billing_type=BillingType.MONTHLY,
        current_charge_date=date(2026, 1, 31),
        billing_day=31,
    )
    assert nxt == date(2026, 2, 28)


def test_yearly_feb29() -> None:
    nxt = calculate_next_charge_date(
        billing_type=BillingType.YEARLY,
        current_charge_date=date(2024, 2, 29),
    )
    assert nxt == date(2025, 2, 28)


def test_every_n_days() -> None:
    nxt = calculate_next_charge_date(
        billing_type=BillingType.EVERY_N_DAYS,
        current_charge_date=date(2026, 7, 1),
        billing_interval=30,
    )
    assert nxt == date(2026, 7, 31)


def test_none_returns_null() -> None:
    assert (
        calculate_next_charge_date(
            billing_type=BillingType.NONE,
            current_charge_date=date(2026, 7, 1),
        )
        is None
    )
