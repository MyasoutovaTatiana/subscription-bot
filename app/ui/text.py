"""
UI Kit — text primitives (titles, blocks, screens, lists).

Правила:
1. HTML parse mode; пользовательский текст — только через ``txt()``.
2. Экран = заголовок + пустая строка + блоки через пустую строку.
3. Поле карточки = «эмодзи Подпись» на первой строке, значение ниже.
4. Жирный (<b>) — только заголовок экрана и имя сущности.
5. Без технических терминов в пользовательском тексте.
"""

from __future__ import annotations

from app.ui.tokens import BLANK_LINE, FIELD_BULLET, LIST_BULLET
from app.utils.telegram import escape_html


def txt(value: str | None) -> str:
    """Escape user-provided text for HTML messages."""
    return escape_html(value)


def title(icon: str, text: str, *, count: int | None = None) -> str:
    """
    Screen / section title.

    Examples::

        title(Icon.SUBSCRIPTION, "Подписки", count=12)
        → 💳 <b>Подписки</b> · 12
    """
    head = f"{icon} <b>{text}</b>" if icon else f"<b>{text}</b>"
    if count is None:
        return head
    return f"{head} {LIST_BULLET} {count}"


def entity_name(icon: str, name: str) -> str:
    """Primary entity line inside a card: 💳 <b>ChatGPT Plus</b>."""
    return f"{icon} <b>{txt(name)}</b>"


def field(icon: str, label: str, *value_lines: str) -> str:
    """
    Labeled content block for cards.

    Example::

        field(Icon.MONEY, "Стоимость", "$20", "≈ 1 860 ₽")
    """
    header = f"{icon} {label}".strip()
    values = [line for line in value_lines if line]
    if not values:
        return header
    return header + "\n" + "\n".join(values)


def bullets(*items: str) -> str:
    """Bullet list for reminders / features."""
    lines = [f"{FIELD_BULLET} {item}" for item in items if item]
    return "\n".join(lines) if lines else "Нет"


def join_blocks(*blocks: str) -> str:
    """Join non-empty blocks with a blank line."""
    return "\n\n".join(b for b in blocks if b)


def screen(heading: str, *blocks: str, footer: str | None = None) -> str:
    """
    Full app screen.

    Structure::

        {heading}

        {block1}

        {block2}

        {footer?}
    """
    parts: list[str] = [heading, BLANK_LINE]
    content = [b for b in blocks if b]
    parts.append(join_blocks(*content) if content else "")
    if footer:
        parts.extend([BLANK_LINE, footer])
    return "\n".join(p for p in parts if p is not None).rstrip()


def prompt(heading: str, hint: str | None = None) -> str:
    """Short step prompt during FSM wizards."""
    if hint:
        return f"{heading}\n{hint}"
    return heading
