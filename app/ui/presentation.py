"""
Compatibility shim — prefer ``from app.ui import …``.

Kept so older imports ``app.ui.presentation`` keep working.
"""

from __future__ import annotations

from app.ui.money import rub_estimate as format_rub_estimate
from app.ui.status import (
    STATUS_EMOJI,
    STATUS_LABELS,
    SubscriptionStatus,
    resolve_subscription_status,
)
from app.ui.text import field as block
from app.ui.text import screen, txt as escape_name
from app.ui.tokens import Copy

RUB_HINT = Copy.RUB_HINT

__all__ = [
    "SubscriptionStatus",
    "STATUS_LABELS",
    "STATUS_EMOJI",
    "RUB_HINT",
    "resolve_subscription_status",
    "format_rub_estimate",
    "block",
    "screen",
    "escape_name",
]
