"""HTML / Telegram formatting helpers."""

from __future__ import annotations

import html


def escape_html(value: str | None) -> str:
    """Escape user-provided text for HTML parse mode."""
    if value is None:
        return ""
    return html.escape(value, quote=False)
