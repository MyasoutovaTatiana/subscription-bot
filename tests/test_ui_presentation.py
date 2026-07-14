"""UI formatting tests (presentation only)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.subscription_cards import format_subscription_card
from app.ui.presentation import SubscriptionStatus, format_rub_estimate, resolve_subscription_status
from app.utils.dates import format_charge_when, format_relative_days


def test_relative_days() -> None:
    today = date(2026, 7, 14)
    assert format_relative_days(date(2026, 7, 14), today=today) == "Сегодня"
    assert format_relative_days(date(2026, 7, 15), today=today) == "Завтра"
    assert format_relative_days(date(2026, 7, 22), today=today) == "через 8 дней"
    assert "просрочено" in format_relative_days(date(2026, 7, 10), today=today)


def test_charge_when_two_lines() -> None:
    text = format_charge_when(date(2026, 7, 22), today=date(2026, 7, 14))
    assert "22 июля 2026" in text
    assert "через 8 дней" in text


def test_rub_estimate_no_cbr() -> None:
    assert "ЦБ" not in format_rub_estimate(None, currency="USD")
    assert format_rub_estimate(None, currency="USD") == "≈ будет рассчитано автоматически"
    assert "1 860" in format_rub_estimate(Decimal("1860"), currency="USD")
    assert format_rub_estimate(Decimal("100"), currency="RUB") == ""


def test_subscription_status() -> None:
    today = date(2026, 7, 14)
    paused = SimpleNamespace(is_active=False, next_charge_date=date(2026, 7, 20))
    overdue = SimpleNamespace(is_active=True, next_charge_date=date(2026, 7, 10))
    soon = SimpleNamespace(is_active=True, next_charge_date=date(2026, 7, 16))
    active = SimpleNamespace(is_active=True, next_charge_date=date(2026, 8, 1))
    assert resolve_subscription_status(paused, today=today) == SubscriptionStatus.PAUSED
    assert resolve_subscription_status(overdue, today=today) == SubscriptionStatus.OVERDUE
    assert resolve_subscription_status(soon, today=today) == SubscriptionStatus.SOON
    assert resolve_subscription_status(active, today=today) == SubscriptionStatus.ACTIVE


def test_card_layout_no_technical_cbr() -> None:
    sub = SimpleNamespace(
        name="ChatGPT Plus",
        category="ai_work",
        amount=Decimal("20.40"),
        currency="USD",
        billing_type="monthly",
        billing_interval=None,
        billing_day=14,
        next_charge_date=date(2026, 7, 22),
        payment_method=SimpleNamespace(name="Иностранная USD"),
        reminder_offsets=[3, 1, 0],
        notes=None,
        is_active=True,
    )
    card = format_subscription_card(
        sub,  # type: ignore[arg-type]
        estimated_rub=Decimal("1860"),
        title="✅ Подписка создана",
        today=date(2026, 7, 14),
    )
    assert "Действия" not in card
    assert "ЦБ" not in card
    assert "💰 Стоимость" in card
    assert "💳 Способ оплаты" in card
    assert "через 8 дней" in card
    assert "🟢 Активна" in card or "🟡" in card
    assert "Каждый месяц" in card
