"""Payment keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.friend import Friend
from app.ui.tokens import Action
from app.utils.callback_data import MenuCb, TxCb


def friends_select_keyboard(
    friends: list[Friend],
    selected_ids: set[int],
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for friend in friends:
        mark = "✅ " if friend.id in selected_ids else ""
        b.button(
            text=f"{mark}{friend.name}",
            callback_data=MenuCb(action="ftoggle", value=str(friend.id)).pack(),
        )
    b.button(text=Action.NEW_FRIEND, callback_data=MenuCb(action="ftoggle", value="new").pack())
    b.button(text=Action.DONE, callback_data=MenuCb(action="ftoggle", value="done").pack())
    b.button(text=Action.NO_FRIENDS, callback_data=MenuCb(action="ftoggle", value="none").pack())
    b.adjust(1)
    return b.as_markup()


def yes_no_keyboard(action: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=Action.YES, callback_data=MenuCb(action=action, value="yes").pack())
    b.button(text=Action.NO, callback_data=MenuCb(action=action, value="no").pack())
    b.adjust(2)
    return b.as_markup()


def split_mode_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Поровну", callback_data=MenuCb(action="sm", value="equal").pack())
    b.button(text="Без деления", callback_data=MenuCb(action="sm", value="none").pack())
    b.adjust(1)
    return b.as_markup()


def confirm_payment_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=Action.SAVE, callback_data=MenuCb(action="pay_confirm", value="yes").pack())
    b.button(text=Action.CANCEL, callback_data=MenuCb(action="pay_confirm", value="no").pack())
    b.adjust(2)
    return b.as_markup()


def payment_saved_keyboard(*, transaction_id: int, has_debts: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_debts:
        b.button(text=Action.OPEN_DEBTS, callback_data=MenuCb(action="nav", value="debts").pack())
    b.button(text=Action.OPEN_PAYMENT, callback_data=TxCb(action="ot_view", tid=transaction_id).pack())
    b.button(text=Action.EDIT, callback_data=TxCb(action="ot_edit", tid=transaction_id).pack())
    b.button(text=Action.HOME, callback_data=MenuCb(action="nav", value="home").pack())
    b.adjust(1)
    return b.as_markup()
