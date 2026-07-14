"""Tests for FSM vs navigation priority filter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.filters.navigation import NotNavigationOrCommand
from app.keyboards.main_menu import BTN_SETTINGS, BTN_UPCOMING, MAIN_MENU_TEXTS
from app.ui.tokens import Nav


def _message(*, text: str | None, entities: list | None = None) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.entities = entities
    return msg


@pytest.mark.asyncio
async def test_filter_allows_ordinary_input() -> None:
    f = NotNavigationOrCommand()
    assert await f(_message(text="1850.50")) is True
    assert await f(_message(text="ChatGPT Plus")) is True
    assert await f(_message(text=None)) is True


@pytest.mark.asyncio
async def test_filter_blocks_all_main_menu_buttons() -> None:
    f = NotNavigationOrCommand()
    assert MAIN_MENU_TEXTS == frozenset(
        {
            Nav.HOME,
            Nav.ADD_SUBSCRIPTION,
            Nav.ONE_TIME,
            Nav.UPCOMING,
            Nav.SUBSCRIPTIONS,
            Nav.DEBTS,
            Nav.SETTINGS,
        }
    )
    for label in MAIN_MENU_TEXTS:
        assert await f(_message(text=label)) is False


@pytest.mark.asyncio
async def test_filter_blocks_slash_commands() -> None:
    f = NotNavigationOrCommand()
    assert await f(_message(text="/start")) is False
    assert await f(_message(text="/help")) is False
    assert await f(_message(text="/cancel")) is False
    assert await f(_message(text="/settings")) is False
    assert await f(_message(text="/settings@my_bot")) is False


@pytest.mark.asyncio
async def test_filter_blocks_bot_command_entity() -> None:
    f = NotNavigationOrCommand()
    entity = MagicMock()
    entity.type = "bot_command"
    entity.offset = 0
    assert await f(_message(text="/start", entities=[entity])) is False


@pytest.mark.asyncio
async def test_upcoming_and_settings_labels_are_blocked() -> None:
    f = NotNavigationOrCommand()
    assert await f(_message(text=BTN_UPCOMING)) is False
    assert await f(_message(text=BTN_SETTINGS)) is False
