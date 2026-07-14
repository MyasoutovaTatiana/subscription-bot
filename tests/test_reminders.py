"""Reminder due-detection and idempotency tests."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from app.models.reminder_delivery import ReminderDelivery
from app.services.reminders import compute_scheduled_at, find_due_reminders, reminder_headline


def test_reminder_headlines() -> None:
    assert "Сегодня" in reminder_headline(0)
    assert "Завтра" in reminder_headline(1)
    assert "Через 3" in reminder_headline(3)


def test_compute_scheduled_at() -> None:
    tz = ZoneInfo("Europe/Moscow")
    scheduled = compute_scheduled_at(date(2026, 7, 20), 3, "10:00", tz)
    assert scheduled.date() == date(2026, 7, 17)
    assert scheduled.hour == 10


def test_find_due_and_idempotency() -> None:
    tz = ZoneInfo("Europe/Moscow")
    charge = date(2026, 7, 20)
    user = SimpleNamespace(timezone="Europe/Moscow")
    sub = SimpleNamespace(
        id=1,
        is_active=True,
        next_charge_date=charge,
        reminder_offsets=[3, 1, 0],
        reminder_time="10:00",
        user=user,
    )
    # At 10:00 Moscow on July 17 — offset 3 is due
    now = datetime(2026, 7, 17, 10, 0, tzinfo=tz)
    due = find_due_reminders([sub], now=now, already_sent_keys=set())
    offsets = {d.offset for d in due}
    assert 3 in offsets
    assert 1 not in offsets

    key = ReminderDelivery.build_unique_key(1, charge, 3)
    due2 = find_due_reminders([sub], now=now, already_sent_keys={key})
    assert all(d.offset != 3 for d in due2)


def test_unique_key_stable() -> None:
    k1 = ReminderDelivery.build_unique_key(5, date(2026, 7, 20), 1)
    k2 = ReminderDelivery.build_unique_key(5, date(2026, 7, 20), 1)
    assert k1 == k2
    assert k1 != ReminderDelivery.build_unique_key(5, date(2026, 7, 20), 0)
