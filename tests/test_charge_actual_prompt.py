"""UX подтверждения списания и экрана «Возникла проблема»."""

from datetime import date

from app.keyboards.subscriptions import charge_confirmed_keyboard, problem_arose_keyboard
from app.services.charge_cards import format_charge_confirmed
from app.ui.tokens import Action, Copy


def test_charge_confirmed_message() -> None:
    text = format_charge_confirmed(next_charge_date=date(2026, 8, 14))
    assert Copy.CHARGE_CONFIRMED in text
    assert Copy.NEXT_CHARGE_LABEL in text
    assert "14 августа" in text


def test_charge_confirmed_no_next() -> None:
    text = format_charge_confirmed(next_charge_date=None)
    assert "Без повторения" in text


def test_problem_arose_keyboard_labels() -> None:
    kb = problem_arose_keyboard(42)
    labels = {btn.text for row in kb.inline_keyboard for btn in row}
    assert Action.NO_MONEY in labels
    assert Action.DATE_CHANGED in labels
    assert Action.PRICE_CHANGED in labels
    assert Action.SUB_CANCELLED in labels
    assert Action.DELETE_SUB in labels
    assert Action.SKIP not in labels
    joined = " ".join(labels)
    assert "Перенести" not in joined
    assert "Пропустить" not in joined


def test_reminder_keyboard_simplified() -> None:
    from app.scheduler.jobs import reminder_actions_keyboard as rem_kb

    kb = rem_kb(7)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert labels == [Action.CONFIRM_CHARGE, Action.PROBLEM]


def test_charge_confirmed_keyboard() -> None:
    kb = charge_confirmed_keyboard(3)
    labels = {btn.text for row in kb.inline_keyboard for btn in row}
    assert Action.OPEN in labels
