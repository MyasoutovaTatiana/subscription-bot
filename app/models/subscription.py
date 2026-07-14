"""Subscription and participant models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.friend import Friend
    from app.models.payment_method import PaymentMethod
    from app.models.user import User


class Subscription(Base, TimestampMixin):
    """Recurring (or one-shot) subscription charge schedule."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    billing_type: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_charge_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
    )
    reminder_offsets: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    reminder_time: Mapped[str] = mapped_column(String(5), nullable=False, default="10:00")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_owner_in_split: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    split_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    payment_method: Mapped[PaymentMethod | None] = relationship()
    participants: Mapped[list[SubscriptionParticipant]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} name={self.name!r}>"


class SubscriptionParticipant(Base, TimestampMixin):
    """Friend attached to a subscription before charge confirmation."""

    __tablename__ = "subscription_participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    friend_id: Mapped[int] = mapped_column(ForeignKey("friends.id", ondelete="CASCADE"), nullable=False)
    share_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    subscription: Mapped[Subscription] = relationship(back_populates="participants")
    friend: Mapped[Friend] = relationship()
