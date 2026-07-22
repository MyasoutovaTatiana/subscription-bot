"""Tests for billing date calculations."""

from datetime import date

import pytest

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


@pytest.mark.parametrize(
    ("billing_day", "january", "february", "march"),
    [
        (29, date(2024, 1, 29), date(2024, 2, 29), date(2024, 3, 29)),
        (30, date(2024, 1, 30), date(2024, 2, 29), date(2024, 3, 30)),
        (31, date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)),
    ],
)
def test_monthly_anchor_returns_after_leap_february(
    billing_day: int,
    january: date,
    february: date,
    march: date,
) -> None:
    after_january = calculate_next_charge_date(
        billing_type=BillingType.MONTHLY,
        current_charge_date=january,
        billing_day=billing_day,
    )
    after_february = calculate_next_charge_date(
        billing_type=BillingType.MONTHLY,
        current_charge_date=february,
        billing_day=billing_day,
    )

    assert after_january == february
    assert after_february == march


def test_yearly_regular_date() -> None:
    assert calculate_next_charge_date(
        billing_type=BillingType.YEARLY,
        current_charge_date=date(2026, 7, 22),
    ) == date(2027, 7, 22)


def test_custom_interval() -> None:
    assert calculate_next_charge_date(
        billing_type=BillingType.CUSTOM,
        current_charge_date=date(2026, 7, 22),
        billing_interval=45,
    ) == date(2026, 9, 5)
