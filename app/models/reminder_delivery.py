"""Reminder delivery idempotency records."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ReminderStatus

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user import User


class ReminderDelivery(Base, TimestampMixin):
    """Tracks scheduled / sent subscription reminders (idempotent)."""

    __tablename__ = "reminder_deliveries"
    __table_args__ = (
        UniqueConstraint("unique_key", name="uq_reminder_deliveries_unique_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    charge_date: Mapped[date] = mapped_column(Date, nullable=False)
    reminder_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReminderStatus.PENDING.value,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    unique_key: Mapped[str] = mapped_column(String(128), nullable=False)

    user: Mapped[User] = relationship(back_populates="reminder_deliveries")
    subscription: Mapped[Subscription] = relationship()

    @staticmethod
    def build_unique_key(subscription_id: int, charge_date: date, offset: int) -> str:
        return f"sub:{subscription_id}:charge:{charge_date.isoformat()}:off:{offset}"

    def __repr__(self) -> str:
        return f"<ReminderDelivery key={self.unique_key} status={self.status}>"
