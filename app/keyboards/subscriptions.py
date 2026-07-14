"""Subscription-related keyboards."""

from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.enums import (
    BILLING_LABELS,
    CATEGORY_LABELS,
    CurrencyCode,
)
from app.models.payment_method import PaymentMethod
from app.models.subscription import Subscription
from app.services.subscription_cards import format_subscription_list_row
from app.ui.tokens import Action
from app.utils.callback_data import MenuCb, SubCb, TxCb


def categories_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat, label in CATEGORY_LABELS.items():
        builder.button(text=label, callback_data=MenuCb(action="cat", value=cat.value).pack())
    builder.adjust(1)
    return builder.as_markup()


def currencies_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code in CurrencyCode:
        builder.button(text=code.value, callback_data=MenuCb(action="cur", value=code.value).pack())
    builder.adjust(4)
    return builder.as_markup()


def billing_types_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    labels = {
        "monthly": "Каждый месяц",
        "every_n_days": "Через несколько дней",
        "yearly": "Каждый год",
        "custom": "Свой интервал",
        "none": "Без повторения",
    }
    for btype, label in BILLING_LABELS.items():
        builder.button(
            text=labels.get(btype.value, label),
            callback_data=MenuCb(action="bill", value=btype.value).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(methods: list[PaymentMethod]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for method in methods:
        builder.button(
            text=method.name,
            callback_data=MenuCb(action="pm", value=str(method.id)).pack(),
        )
    builder.button(text=Action.NEW_METHOD, callback_data=MenuCb(action="pm", value="new").pack())
    builder.button(text=Action.SKIP, callback_data=MenuCb(action="pm", value="skip").pack())
    builder.adjust(1)
    return builder.as_markup()


def reminders_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Как обычно",
        callback_data=MenuCb(action="rem", value="default").pack(),
    )
    builder.button(text="Только в день", callback_data=MenuCb(action="rem", value="0").pack())
    builder.button(text="За день и в день", callback_data=MenuCb(action="rem", value="1,0").pack())
    builder.button(text="Без напоминаний", callback_data=MenuCb(action="rem", value="none").pack())
    builder.adjust(1)
    return builder.as_markup()


def friends_step_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.NO_FRIENDS, callback_data=MenuCb(action="fr", value="none").pack())
    builder.button(text=Action.LATER, callback_data=MenuCb(action="fr", value="later").pack())
    builder.adjust(2)
    return builder.as_markup()


def confirm_subscription_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.CREATE, callback_data=MenuCb(action="sub_confirm", value="yes").pack())
    builder.button(text=f"❌ {Action.CANCEL}", callback_data=MenuCb(action="sub_confirm", value="no").pack())
    builder.adjust(2)
    return builder.as_markup()


def subscription_card_keyboard(sub: Subscription) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.EDIT, callback_data=SubCb(action="edit", sid=sub.id).pack())
    if sub.is_active:
        builder.button(text=Action.PAUSE, callback_data=SubCb(action="off", sid=sub.id).pack())
    else:
        builder.button(text=Action.RESUME, callback_data=SubCb(action="on", sid=sub.id).pack())
    builder.button(text=Action.DELETE, callback_data=SubCb(action="del", sid=sub.id).pack())
    builder.button(text=Action.BACK, callback_data=SubCb(action="list", sid=0).pack())
    builder.adjust(2, 2)
    return builder.as_markup()


def confirm_delete_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.CONFIRM_DELETE, callback_data=SubCb(action="del_yes", sid=subscription_id).pack())
    builder.button(text=Action.CANCEL, callback_data=SubCb(action="view", sid=subscription_id).pack())
    builder.adjust(2)
    return builder.as_markup()


def subscriptions_list_keyboard(
    subs: list[Subscription],
    *,
    today: date | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for sub in subs:
        text = format_subscription_list_row(sub, today=today)
        # Telegram button text limit ~64 chars
        if len(text) > 60:
            text = text[:57] + "…"
        builder.button(
            text=text,
            callback_data=SubCb(action="view", sid=sub.id).pack(),
        )
    builder.adjust(1)
    return builder.as_markup()


def edit_fields_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        ("name", "Название"),
        ("amount", "Сумма"),
        ("currency", "Валюта"),
        ("next_charge_date", "Дата"),
        ("notes", "Заметка"),
    ]
    for key, label in fields:
        builder.button(text=label, callback_data=SubCb(action=f"ef_{key}", sid=subscription_id).pack())
    builder.button(text=Action.BACK, callback_data=SubCb(action="view", sid=subscription_id).pack())
    builder.adjust(2)
    return builder.as_markup()


def problem_arose_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    """«Что произошло?» after charge reminder."""
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.NO_MONEY, callback_data=SubCb(action="prob_nomoney", sid=subscription_id).pack())
    builder.button(text=Action.DATE_CHANGED, callback_data=SubCb(action="prob_date", sid=subscription_id).pack())
    builder.button(text=Action.PRICE_CHANGED, callback_data=SubCb(action="prob_price", sid=subscription_id).pack())
    builder.button(text=Action.SUB_CANCELLED, callback_data=SubCb(action="prob_cancel", sid=subscription_id).pack())
    builder.button(text=Action.DELETE_SUB, callback_data=SubCb(action="prob_del", sid=subscription_id).pack())
    builder.button(text=Action.BACK, callback_data=SubCb(action="view", sid=subscription_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def charge_confirmed_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.OPEN, callback_data=SubCb(action="view", sid=subscription_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def charge_actual_rub_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    """Legacy ask-first keyboard (kept for tests / fallback)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.SKIP, callback_data=SubCb(action="chg_skip", sid=subscription_id).pack())
    builder.button(text=Action.CANCEL_CROSS, callback_data=SubCb(action="chg_cancel", sid=subscription_id).pack())
    builder.adjust(2)
    return builder.as_markup()


def charge_card_keyboard(
    transaction_id: int,
    *,
    subscription_id: int = 0,
    show_rate: bool = True,
) -> InlineKeyboardMarkup:
    """Actions on a saved charge card."""
    builder = InlineKeyboardBuilder()
    builder.button(text=Action.EDIT_AMOUNT, callback_data=TxCb(action="amt", tid=transaction_id).pack())
    builder.button(text=Action.EDIT_DATE, callback_data=TxCb(action="date", tid=transaction_id).pack())
    if show_rate:
        builder.button(text=Action.EDIT_RATE, callback_data=TxCb(action="rate", tid=transaction_id).pack())
    builder.button(text=Action.RECALC_DEBTS, callback_data=TxCb(action="recalc", tid=transaction_id).pack())
    builder.button(text=Action.UNDO_CHARGE, callback_data=TxCb(action="undo", tid=transaction_id).pack())
    builder.button(text=Action.DELETE_CHARGE, callback_data=TxCb(action="del", tid=transaction_id).pack())
    if subscription_id:
        builder.button(text=Action.BACK, callback_data=SubCb(action="view", sid=subscription_id).pack())
    else:
        builder.button(text=Action.BACK, callback_data=TxCb(action="back", tid=transaction_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def confirm_charge_action_keyboard(transaction_id: int, *, action: str) -> InlineKeyboardMarkup:
    """Confirm undo / delete charge."""
    builder = InlineKeyboardBuilder()
    confirm_label = Action.CONFIRM_DELETE if action == "del" else Action.CONFIRM_UNDO
    builder.button(
        text=confirm_label,
        callback_data=TxCb(action=f"{action}_yes", tid=transaction_id).pack(),
    )
    builder.button(text=Action.CANCEL, callback_data=TxCb(action="view", tid=transaction_id).pack())
    builder.adjust(1)
    return builder.as_markup()
