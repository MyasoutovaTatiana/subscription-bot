"""UI Kit contract tests."""

from decimal import Decimal

from app.ui import (
    Action,
    Icon,
    Nav,
    Copy,
    entity_name,
    field,
    money,
    money_with_estimate,
    screen,
    success_screen,
    title,
)


def test_screen_structure() -> None:
    text = screen(
        title(Icon.SUBSCRIPTION, "Подписки", count=2),
        field(Icon.MONEY, "Стоимость", "$20"),
        footer=Copy.RUB_HINT,
    )
    assert "💳 <b>Подписки</b> · 2" in text
    assert "💰 Стоимость\n$20" in text
    assert text.count("\n\n") >= 2
    assert Copy.RUB_HINT in text


def test_money_components() -> None:
    assert money(Decimal("20"), "USD") == "$20"
    body = money_with_estimate(Decimal("20.40"), "USD", estimated_rub=Decimal("1860"))
    assert body.startswith("$20,40")
    assert "≈" in body
    assert "1 860" in body


def test_nav_and_actions_stable() -> None:
    assert Nav.HOME.startswith("🏠")
    assert Action.PAUSE.startswith("⏸")
    assert Action.EDIT.startswith("✏️")
    assert Action.SKIP.startswith("⏭")
    assert Action.CANCEL_CROSS.startswith("❌")


def test_success_and_entity() -> None:
    msg = success_screen("Подписка создана", entity_name(Icon.SUBSCRIPTION, "ChatGPT"))
    assert msg.startswith("✅")
    assert "<b>ChatGPT</b>" in msg
    assert "ЦБ" not in msg


def test_bank_differs_copy() -> None:
    assert "отличаться" in Copy.BANK_DIFFERS
    assert Copy.RATE_CBR_LABEL == "Курс ЦБ"


def test_rate_line_two_decimals() -> None:
    from app.ui import rate_line

    line = rate_line("Курс ЦБ", Decimal("76.6213"), "USD")
    assert "1 USD = 76,62 ₽" in line
    assert "76,6213" not in line
