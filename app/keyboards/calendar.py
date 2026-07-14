"""Inline calendar helpers for date picking."""

from __future__ import annotations

import calendar
from datetime import date

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils.callback_data import MenuCb

_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS_RU = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def payment_date_quick_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🟢 Сегодня", callback_data=MenuCb(action="pdate", value="today").pack())
    b.button(text="🟡 Вчера", callback_data=MenuCb(action="pdate", value="yesterday").pack())
    b.button(text="📅 Выбрать дату", callback_data=MenuCb(action="pdate", value="pick").pack())
    b.adjust(1)
    return b.as_markup()


def calendar_keyboard(year: int, month: int, *, action_prefix: str = "cal") -> InlineKeyboardMarkup:
    """Month grid. Callbacks: ``{prefix}_d:YYYY-MM-DD``, ``{prefix}_m:YYYY-MM``, ``{prefix}_x`` close/noop."""
    b = InlineKeyboardBuilder()
    title = f"{_MONTHS_RU[month]} {year}"
    b.button(text=title, callback_data=MenuCb(action=action_prefix, value="noop").pack())
    b.adjust(1)

    for wd in _WEEKDAYS:
        b.button(text=wd, callback_data=MenuCb(action=action_prefix, value="noop").pack())
    b.adjust(7)

    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    for week in weeks:
        for day in week:
            if day == 0:
                b.button(text="·", callback_data=MenuCb(action=action_prefix, value="noop").pack())
            else:
                iso = date(year, month, day).isoformat()
                b.button(
                    text=str(day),
                    callback_data=MenuCb(action=action_prefix, value=f"d:{iso}").pack(),
                )
        b.adjust(7)

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    b.button(
        text="‹",
        callback_data=MenuCb(action=action_prefix, value=f"m:{prev_y:04d}-{prev_m:02d}").pack(),
    )
    b.button(text="·", callback_data=MenuCb(action=action_prefix, value="noop").pack())
    b.button(
        text="›",
        callback_data=MenuCb(action=action_prefix, value=f"m:{next_y:04d}-{next_m:02d}").pack(),
    )
    b.adjust(3)
    return b.as_markup()


def ot_currencies_keyboard() -> InlineKeyboardMarkup:
    """Primary currencies with flags for one-time payment wizard."""
    flags = [
        ("🇷🇺 RUB", "RUB"),
        ("🇺🇸 USD", "USD"),
        ("🇪🇺 EUR", "EUR"),
        ("🇨🇳 CNY", "CNY"),
        ("🇯🇵 JPY", "JPY"),
    ]
    b = InlineKeyboardBuilder()
    for label, code in flags:
        b.button(text=label, callback_data=MenuCb(action="cur", value=code).pack())
    b.adjust(1)
    return b.as_markup()
