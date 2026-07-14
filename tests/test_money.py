"""Tests for money utilities."""

from decimal import Decimal

import pytest

from app.utils.money import MoneyError, format_money, format_number, parse_amount, quantize_money


def test_parse_amount_basic() -> None:
    assert parse_amount("20") == Decimal("20")
    assert parse_amount("20,50") == Decimal("20.50")
    assert parse_amount("1 850,40") == Decimal("1850.40")


def test_parse_amount_rejects_zero_and_negative() -> None:
    with pytest.raises(MoneyError):
        parse_amount("0")
    with pytest.raises(MoneyError):
        parse_amount("-10")


def test_quantize_and_format() -> None:
    assert quantize_money(Decimal("1850.406")) == Decimal("1850.41")
    assert format_number(Decimal("1850.40")) == "1 850,4"
    assert format_money(Decimal("20"), "USD") == "$20"
    assert format_money(Decimal("1850.40"), "RUB") == "1 850,40 ₽"
    assert format_money(Decimal("1850"), "RUB") == "1 850 ₽"
