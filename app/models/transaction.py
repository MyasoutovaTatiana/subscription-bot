"""Transaction and split models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.debt import Debt
    from app.models.friend import Friend
    from app.models.payment_method import PaymentMethod
    from app.models.subscription import Subscription
    from app.models.user import User


class Transaction(Base, TimestampMixin):
    """Recorded payment (subscription charge or one-time)."""

    __tablename__ = "transactions"
    __table_args__ = (
        Index(
            "uq_transactions_subscription_id_transaction_date",
            "subscription_id",
            "transaction_date",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    original_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_rub_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_rub_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    is_rate_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    conversion_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
    )
    split_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    include_owner_in_split: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="transactions")
    subscription: Mapped[Subscription | None] = relationship()
    payment_method: Mapped[PaymentMethod | None] = relationship()
    splits: Mapped[list[TransactionSplit]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
    debts: Mapped[list[Debt]] = relationship(back_populates="transaction")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} name={self.name!r}>"


class TransactionSplit(Base, TimestampMixin):
    """Share of a transaction for owner or a friend."""

    __tablename__ = "transaction_splits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    friend_id: Mapped[int | None] = mapped_column(
        ForeignKey("friends.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    share_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    transaction: Mapped[Transaction] = relationship(back_populates="splits")
    friend: Mapped[Friend | None] = relationship()
