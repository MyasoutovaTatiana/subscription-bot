"""Debt keyboards via UI Kit actions."""

from __future__ import annotations

from decimal import Decimal

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.debt import Debt
from app.models.enums import DEBT_STATUS_LABELS, DebtStatus
from app.ui import money
from app.ui.tokens import Action
from app.utils.callback_data import DebtCb


def _status_dot(status: str) -> str:
    if status == DebtStatus.NEEDS_REVIEW.value:
        return "🟠"
    if status == DebtStatus.PAID.value:
        return "🟢"
    return "🟡"


def debts_list_keyboard(debts: list[Debt]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for debt in debts:
        name = debt.friend.name if debt.friend else "Друг"
        amount = money(Decimal(debt.amount_rub), "RUB")
        text = f"{_status_dot(debt.status)} {name} · {amount}"
        if len(text) > 60:
            text = text[:57] + "…"
        b.button(
            text=text,
            callback_data=DebtCb(action="view", did=debt.id).pack(),
        )
    b.adjust(1)
    return b.as_markup()


def debt_owner_keyboard(debt: Debt) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if debt.status == DebtStatus.NEEDS_REVIEW.value:
        b.button(text=Action.MONEY_RECEIVED, callback_data=DebtCb(action="money_ok", did=debt.id).pack())
        b.button(text=Action.MONEY_NOT_RECEIVED, callback_data=DebtCb(action="money_no", did=debt.id).pack())
        b.button(text=Action.CHECK_LATER, callback_data=DebtCb(action="check_later", did=debt.id).pack())
    else:
        b.button(text=Action.SHARE_LINK, callback_data=DebtCb(action="share", did=debt.id).pack())
        b.button(text=Action.MONEY_RECEIVED, callback_data=DebtCb(action="money_ok", did=debt.id).pack())
        b.button(text=Action.AMOUNT, callback_data=DebtCb(action="edit", did=debt.id).pack())
        b.button(text=Action.CANCEL_ITEM, callback_data=DebtCb(action="cancel", did=debt.id).pack())
    b.button(text=Action.BACK, callback_data=DebtCb(action="list", did=0).pack())
    b.adjust(1)
    return b.as_markup()


def debt_actions_keyboard(debt_id: int) -> InlineKeyboardMarkup:
    """Backwards-compatible wrapper (active debt)."""
    b = InlineKeyboardBuilder()
    b.button(text=Action.SHARE_LINK, callback_data=DebtCb(action="share", did=debt_id).pack())
    b.button(text=Action.MONEY_RECEIVED, callback_data=DebtCb(action="money_ok", did=debt_id).pack())
    b.button(text=Action.AMOUNT, callback_data=DebtCb(action="edit", did=debt_id).pack())
    b.button(text=Action.CANCEL_ITEM, callback_data=DebtCb(action="cancel", did=debt_id).pack())
    b.button(text=Action.BACK, callback_data=DebtCb(action="list", did=0).pack())
    b.adjust(1)
    return b.as_markup()


def friend_debt_keyboard(debt_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=Action.I_PAID, callback_data=DebtCb(action="friend_paid", did=debt_id).pack())
    b.button(text=Action.PAY_LATER, callback_data=DebtCb(action="friend_later", did=debt_id).pack())
    b.adjust(1)
    return b.as_markup()


def debt_status_label(status: str) -> str:
    try:
        return DEBT_STATUS_LABELS[DebtStatus(status)]
    except ValueError:
        return status
