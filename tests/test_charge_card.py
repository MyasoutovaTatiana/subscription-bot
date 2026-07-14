"""Charge card presentation tests."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.keyboards.subscriptions import charge_card_keyboard
from app.services.charge_cards import format_amount_updated, format_charge_card
from app.ui.tokens import Action, Copy


def test_format_charge_card_fields() -> None:
    tx = SimpleNamespace(
        name="ChatGPT Plus",
        original_amount=Decimal("20.40"),
        original_currency="USD",
        estimated_rub_amount=Decimal("1563.07"),
        actual_rub_amount=Decimal("1589.32"),
        transaction_date=date(2026, 7, 14),
    )
    text = format_charge_card(tx, next_charge_date=date(2026, 8, 14))  # type: ignore[arg-type]
    assert Copy.CHARGE_SAVED in text
    assert "ChatGPT Plus" in text
    assert Copy.ORIGINAL_AMOUNT_LABEL in text
    assert "$20,40" in text
    assert Copy.ESTIMATED_RUB_LABEL in text
    assert "1 563,07" in text
    assert Copy.ACTUAL_RUB_LABEL in text
    assert "1 589,32" in text
    assert Copy.CHARGE_DATE_LABEL in text
    assert "14 июля 2026" in text
    assert Copy.NEXT_CHARGE_LABEL in text


def test_amount_updated_copy() -> None:
    text = format_amount_updated(was=Decimal("1563.07"), now=Decimal("1589.32"))
    assert Copy.AMOUNT_UPDATED in text
    assert "Было: 1 563,07 ₽" in text
    assert "Стало: 1 589,32 ₽" in text
    assert Copy.DEBTS_RECALCULATED in text


def test_charge_card_keyboard_actions() -> None:
    kb = charge_card_keyboard(7, subscription_id=3, show_rate=True)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert Action.EDIT_AMOUNT in labels
    assert Action.EDIT_DATE in labels
    assert Action.EDIT_RATE in labels
    assert Action.RECALC_DEBTS in labels
    assert Action.UNDO_CHARGE in labels
    assert Action.DELETE_CHARGE in labels
    assert Action.BACK in labels

    kb_rub = charge_card_keyboard(7, subscription_id=3, show_rate=False)
    labels_rub = [btn.text for row in kb_rub.inline_keyboard for btn in row]
    assert Action.EDIT_RATE not in labels_rub
