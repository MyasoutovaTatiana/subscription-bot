"""User model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import DEFAULT_REMINDER_OFFSETS

if TYPE_CHECKING:
    from app.models.debt import Debt
    from app.models.friend import Friend
    from app.models.payment_method import PaymentMethod
    from app.models.reminder_delivery import ReminderDelivery
    from app.models.subscription import Subscription
    from app.models.transaction import Transaction


class User(Base, TimestampMixin):
    """Application user mapped from a Telegram account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    default_reminder_time: Mapped[str] = mapped_column(String(5), nullable=False, default="10:00")
    default_reminder_offsets: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: list(DEFAULT_REMINDER_OFFSETS),
    )

    payment_methods: Mapped[list[PaymentMethod]] = relationship(back_populates="user")
    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="user")
    friends: Mapped[list[Friend]] = relationship(back_populates="user")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="user")
    debts: Mapped[list[Debt]] = relationship(back_populates="user")
    reminder_deliveries: Mapped[list[ReminderDelivery]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} tg={self.telegram_user_id}>"
