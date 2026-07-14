"""Debt model."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import DebtStatus

if TYPE_CHECKING:
    from app.models.friend import Friend
    from app.models.transaction import Transaction
    from app.models.user import User


class Debt(Base, TimestampMixin):
    """Money owed by a friend for a transaction."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    friend_id: Mapped[int] = mapped_column(ForeignKey("friends.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    original_share_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    original_share_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DebtStatus.ACTIVE.value, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    payer_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    payment_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    user: Mapped[User] = relationship(back_populates="debts")
    transaction: Mapped[Transaction] = relationship(back_populates="debts")
    friend: Mapped[Friend] = relationship()

    def __repr__(self) -> str:
        return f"<Debt id={self.id} status={self.status}>"
