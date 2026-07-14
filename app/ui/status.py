"""UI Kit — status badges for subscriptions and similar entities."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from app.models.subscription import Subscription
from app.ui.tokens import StatusDot


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    SOON = "soon"
    OVERDUE = "overdue"
    PAUSED = "paused"


STATUS_LABELS: dict[SubscriptionStatus, str] = {
    SubscriptionStatus.ACTIVE: f"{StatusDot.OK} Активна",
    SubscriptionStatus.SOON: f"{StatusDot.WARN} Скоро списание",
    SubscriptionStatus.OVERDUE: f"{StatusDot.DANGER} Просрочена",
    SubscriptionStatus.PAUSED: f"{StatusDot.MUTED} Приостановлена",
}

STATUS_EMOJI: dict[SubscriptionStatus, str] = {
    SubscriptionStatus.ACTIVE: StatusDot.OK,
    SubscriptionStatus.SOON: StatusDot.WARN,
    SubscriptionStatus.OVERDUE: StatusDot.DANGER,
    SubscriptionStatus.PAUSED: StatusDot.MUTED,
}


def resolve_subscription_status(
    sub: Subscription,
    *,
    today: date | None = None,
    soon_days: int = 3,
) -> SubscriptionStatus:
    if not sub.is_active:
        return SubscriptionStatus.PAUSED
    if sub.next_charge_date is None:
        return SubscriptionStatus.ACTIVE
    day = today or date.today()
    if sub.next_charge_date < day:
        return SubscriptionStatus.OVERDUE
    if 0 <= (sub.next_charge_date - day).days <= soon_days:
        return SubscriptionStatus.SOON
    return SubscriptionStatus.ACTIVE


def status_line(status: SubscriptionStatus) -> str:
    return STATUS_LABELS[status]


def status_emoji(status: SubscriptionStatus) -> str:
    return STATUS_EMOJI[status]
