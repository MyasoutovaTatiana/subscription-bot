"""Debt / split calculator tests."""

from decimal import Decimal

import pytest

from app.services.debt_calculator import calculate_split, split_equal, split_percent
from app.models.enums import SplitMode
from app.utils.money import MoneyError


def test_split_equal_basic() -> None:
    shares = split_equal(Decimal("100.00"), friend_ids=[1, 2], include_owner=True)
    assert len(shares) == 3
    assert sum(s.amount_rub for s in shares) == Decimal("100.00")
    assert all(s.amount_rub == Decimal("33.33") or s.amount_rub == Decimal("33.34") for s in shares)
    owner = next(s for s in shares if s.is_owner)
    assert owner.amount_rub == Decimal("33.34")


def test_split_equal_remainder_without_owner() -> None:
    shares = split_equal(Decimal("100.00"), friend_ids=[1, 2, 3], include_owner=False)
    assert sum(s.amount_rub for s in shares) == Decimal("100.00")
    assert shares[-1].amount_rub == Decimal("33.34")


def test_split_percent() -> None:
    shares = split_percent(
        Decimal("200.00"),
        percents=[
            (None, True, Decimal("50")),
            (1, False, Decimal("25")),
            (2, False, Decimal("25")),
        ],
    )
    assert shares[0].amount_rub == Decimal("100.00")
    assert shares[1].amount_rub == Decimal("50.00")


def test_split_percent_must_be_100() -> None:
    with pytest.raises(MoneyError):
        split_percent(
            Decimal("100"),
            percents=[(None, True, Decimal("40")), (1, False, Decimal("40"))],
        )


def test_zero_payment_rejected() -> None:
    with pytest.raises(MoneyError):
        calculate_split(SplitMode.EQUAL, Decimal("0"), friend_ids=[1], include_owner=True)
    with pytest.raises(MoneyError):
        calculate_split(SplitMode.EQUAL, Decimal("-5"), friend_ids=[1], include_owner=True)
