"""Reminder planning and due detection (business logic without Telegram IO)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.subscription import Subscription
from app.models.reminder_delivery import ReminderDelivery


@dataclass(frozen=True, slots=True)
class DueReminder:
    subscription: Subscription
    charge_date: date
    offset: int
    scheduled_at: datetime
    unique_key: str


def reminder_headline(offset: int) -> str:
    if offset == 0:
        return "Сегодня ожидается списание"
    if offset == 1:
        return "Завтра спишется"
    return f"Через {offset} дня спишется" if offset < 5 else f"Через {offset} дней спишется"


def compute_scheduled_at(
    charge_date: date,
    offset: int,
    reminder_time: str,
    tz: ZoneInfo,
) -> datetime:
    """Local scheduled datetime for a reminder, returned as aware datetime."""
    hour, minute = (int(x) for x in reminder_time.split(":"))
    local_day = charge_date - timedelta(days=offset)
    local_dt = datetime.combine(local_day, time(hour=hour, minute=minute), tzinfo=tz)
    return local_dt


def find_due_reminders(
    subscriptions: list[Subscription],
    *,
    now: datetime,
    already_sent_keys: set[str],
) -> list[DueReminder]:
    """
    Find reminders that should be sent at ``now``.

    A reminder is due when scheduled_at <= now and unique_key not yet delivered.
    """
    due: list[DueReminder] = []
    for sub in subscriptions:
        if not sub.is_active or sub.next_charge_date is None:
            continue
        try:
            tz = ZoneInfo(sub.user.timezone) if sub.user else ZoneInfo("Europe/Moscow")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("Europe/Moscow")
        reminder_time = sub.reminder_time or "10:00"
        for offset in sub.reminder_offsets or []:
            key = ReminderDelivery.build_unique_key(sub.id, sub.next_charge_date, offset)
            if key in already_sent_keys:
                continue
            scheduled = compute_scheduled_at(sub.next_charge_date, offset, reminder_time, tz)
            if scheduled <= now:
                due.append(
                    DueReminder(
                        subscription=sub,
                        charge_date=sub.next_charge_date,
                        offset=offset,
                        scheduled_at=scheduled,
                        unique_key=key,
                    )
                )
    return due
