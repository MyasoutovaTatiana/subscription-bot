"""
UI Kit — feedback messages: success, error, warning, notice.
"""

from __future__ import annotations

from app.ui.text import screen
from app.ui.tokens import Copy, Icon


def success_title(text: str) -> str:
    return f"{Icon.CHECK} <b>{text}</b>"


def error_title(text: str) -> str:
    return f"{Icon.CROSS} <b>{text}</b>"


def warning_title(text: str) -> str:
    return f"{Icon.WARN} <b>{text}</b>"


def info_title(text: str) -> str:
    return f"{Icon.INFO} <b>{text}</b>"


def success_screen(text: str, *blocks: str, footer: str | None = None) -> str:
    return screen(success_title(text), *blocks, footer=footer)


def error_screen(text: str, *blocks: str, footer: str | None = None) -> str:
    return screen(error_title(text), *blocks, footer=footer)


def warning_screen(text: str, *blocks: str, footer: str | None = None) -> str:
    return screen(warning_title(text), *blocks, footer=footer)


def notice_screen(text: str, *blocks: str, footer: str | None = None) -> str:
    return screen(info_title(text), *blocks, footer=footer)


def toast_cancelled() -> str:
    return f"{Icon.CROSS} {Copy.CANCELLED}"


def toast_ok(detail: str | None = None) -> str:
    if detail:
        return f"{Icon.CHECK} {detail}"
    return f"{Icon.CHECK} {Copy.SAVED}"


def human_error(message: str) -> str:
    """Sanitize exception text for user-facing alerts."""
    banned = (
        "offset",
        "utc",
        "callback",
        "json",
        "scheduler",
        "cron",
        "interval",
        "config",
        "traceback",
        "sqlalchemy",
        "asyncio",
        "none",
        "null",
    )
    cleaned = message.strip()
    lower = cleaned.lower()
    # Allow Russian messages; block English tech dumps
    if any(word in lower for word in banned) and any(c.isascii() and c.isalpha() for c in cleaned):
        # If looks like mixed tech English
        tech_hits = sum(1 for w in banned if w in lower)
        if tech_hits >= 1 and ("error" in lower or "exception" in lower or "traceback" in lower):
            return "Что-то пошло не так. Попробуй ещё раз."
    return cleaned
