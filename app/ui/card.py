"""UI Kit — card builders for recurring entity layouts."""

from __future__ import annotations

from app.ui.text import entity_name, field, screen
from app.ui.tokens import Copy, Icon


def entity_card(
    *,
    heading: str,
    name_icon: str,
    name: str,
    status: str | None = None,
    fields: list[str],
    footer: str | None = None,
) -> str:
    """
    Standard entity card.

    Order: heading → status? → name → fields… → footer?
    """
    blocks: list[str] = []
    if status:
        blocks.append(status)
    blocks.append(entity_name(name_icon, name))
    blocks.extend(fields)
    return screen(heading, *blocks, footer=footer)


def cost_field(body: str) -> str:
    return field(Icon.MONEY, "Стоимость", body)


def charge_date_field(body: str) -> str:
    return field(Icon.CALENDAR, "Следующее списание", body)


def repeat_field(body: str) -> str:
    return field(Icon.REPEAT, "Повтор", body)


def payment_method_field(body: str) -> str:
    return field(Icon.CARD, "Способ оплаты", body)


def reminders_field(body: str) -> str:
    return field(Icon.BELL, "Напоминания", body)


def note_field(body: str) -> str:
    return field(Icon.NOTE, "Заметка", body)


def debts_total_field(body: str) -> str:
    return field(Icon.MONEY, "Всего", body)


def rub_hint_footer() -> str:
    return Copy.RUB_HINT
