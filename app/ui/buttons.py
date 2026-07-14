"""
UI Kit — inline / reply button conventions.

Handlers и keyboards берут подписи только из ``Action`` / ``Nav``.
Разметка: reply = навигация приложения; inline = действия на экране.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.ui.tokens import Action, Nav


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent app shell (tab bar)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=Nav.HOME)],
            [KeyboardButton(text=Nav.SUBSCRIPTIONS), KeyboardButton(text=Nav.UPCOMING)],
            [KeyboardButton(text=Nav.DEBTS), KeyboardButton(text=Nav.ONE_TIME)],
            [KeyboardButton(text=Nav.ADD_SUBSCRIPTION), KeyboardButton(text=Nav.SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def pair_row(*labels_and_data: tuple[str, str]) -> list[InlineKeyboardButton]:
    """Build a row of inline buttons: (label, callback_data)."""
    return [InlineKeyboardButton(text=label, callback_data=data) for label, data in labels_and_data]


def confirm_cancel_keyboard(*, confirm_data: str, cancel_data: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=Action.CREATE if "confirm" in confirm_data or "yes" in confirm_data else Action.SAVE, callback_data=confirm_data)
    b.button(text=f"❌ {Action.CANCEL}", callback_data=cancel_data)
    b.adjust(2)
    return b.as_markup()


def back_button(callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=Action.BACK, callback_data=callback_data)
