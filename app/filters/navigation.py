"""Filters so FSM text steps do not steal navigation or Telegram commands."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.keyboards.main_menu import MAIN_MENU_TEXTS


class NotNavigationOrCommand(BaseFilter):
    """Pass only for ordinary user input inside an FSM step.

    Main-menu reply buttons and Telegram commands must reach their own
    handlers with higher priority than the current FSM state.
    """

    async def __call__(self, message: Message) -> bool:
        text = message.text
        if text is None:
            return True
        if text in MAIN_MENU_TEXTS:
            return False
        if message.entities:
            for entity in message.entities:
                if entity.type == "bot_command" and entity.offset == 0:
                    return False
        if text.startswith("/"):
            return False
        return True
