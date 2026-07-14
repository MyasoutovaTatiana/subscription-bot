"""Date formatting and parsing helpers."""

from __future__ import annotations

from datetime import date, datetime

MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_date_ru(value: date) -> str:
    """Format date as ``20 июля 2026``."""
    return f"{value.day} {MONTHS_RU[value.month]} {value.year}"


def format_date_ru_short(value: date) -> str:
    """Format date as ``14 августа`` (without year)."""
    return f"{value.day} {MONTHS_RU[value.month]}"


def days_until(target: date, *, today: date | None = None) -> int:
    """Signed day delta: negative = overdue."""
    day = today or date.today()
    return (target - day).days


def _plural_days(n: int) -> str:
    if 11 <= (n % 100) <= 14:
        return "дней"
    mod = n % 10
    if mod == 1:
        return "день"
    if mod in {2, 3, 4}:
        return "дня"
    return "дней"


def format_relative_days(target: date, *, today: date | None = None) -> str:
    """
    Relative charge wording for UI.

    Examples: ``Сегодня``, ``Завтра``, ``через 8 дней``, ``просрочено на 2 дня``.
    """
    delta = days_until(target, today=today)
    if delta == 0:
        return "Сегодня"
    if delta == 1:
        return "Завтра"
    if delta == 2:
        return "Послезавтра"
    if delta > 2:
        return f"через {delta} {_plural_days(delta)}"
    n = abs(delta)
    return f"просрочено на {n} {_plural_days(n)}"


def format_charge_when(target: date, *, today: date | None = None) -> str:
    """
    Two-line charge date for cards:

    14 июля 2026
    через 8 дней
    """
    return f"{format_date_ru(target)}\n{format_relative_days(target, today=today)}"


def parse_user_date(raw: str) -> date:
    """
    Parse date from user input.

    Supported: ``DD.MM.YYYY``, ``YYYY-MM-DD``.
    """
    text = raw.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Напиши дату как 20.07.2026")
