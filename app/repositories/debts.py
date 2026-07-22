"""Debt repository."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.debt import Debt
from app.models.enums import OPEN_DEBT_STATUSES, DebtStatus


class DebtRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def new_share_token() -> str:
        return secrets.token_urlsafe(12)

    async def create(self, **kwargs) -> Debt:
        if "share_token" not in kwargs or kwargs.get("share_token") is None:
            kwargs["share_token"] = self.new_share_token()
        debt = Debt(**kwargs)
        self._session.add(debt)
        await self._session.flush()
        return debt

    async def get_for_user(self, debt_id: int, user_id: int) -> Debt | None:
        result = await self._session.execute(
            select(Debt)
            .options(
                selectinload(Debt.friend),
                selectinload(Debt.transaction),
                selectinload(Debt.user),
            )
            .where(Debt.id == debt_id, Debt.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, debt_id: int) -> Debt | None:
        result = await self._session.execute(
            select(Debt)
            .options(
                selectinload(Debt.friend),
                selectinload(Debt.transaction),
                selectinload(Debt.user),
            )
            .where(Debt.id == debt_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_share_token(self, token: str) -> Debt | None:
        result = await self._session.execute(
            select(Debt)
            .options(
                selectinload(Debt.friend),
                selectinload(Debt.transaction),
                selectinload(Debt.user),
            )
            .where(Debt.share_token == token)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def claim_share_token(self, token: str, telegram_user_id: int) -> bool:
        """Atomically bind an open debt link to its first Telegram user.

        Reopening the link by the already-bound payer is allowed. A different
        user, a closed debt, or an invalid token cannot change the binding.
        """
        statuses = [s.value for s in OPEN_DEBT_STATUSES]
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.share_token == token,
                Debt.status.in_(statuses),
                or_(
                    Debt.payer_telegram_id.is_(None),
                    Debt.payer_telegram_id == telegram_user_id,
                ),
            )
            .values(payer_telegram_id=telegram_user_id)
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def ensure_share_token(self, debt: Debt) -> str:
        if not debt.share_token:
            debt.share_token = self.new_share_token()
            await self._session.flush()
        return debt.share_token

    async def list_open(self, user_id: int) -> list[Debt]:
        statuses = [s.value for s in OPEN_DEBT_STATUSES]
        result = await self._session.execute(
            select(Debt)
            .options(selectinload(Debt.friend), selectinload(Debt.transaction))
            .where(Debt.user_id == user_id, Debt.status.in_(statuses))
            .order_by(Debt.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_active(self, user_id: int) -> list[Debt]:
        """Alias for open debts (active + needs review)."""
        return await self.list_open(user_id)

    async def total_open_rub(self, user_id: int) -> Decimal:
        statuses = [s.value for s in OPEN_DEBT_STATUSES]
        result = await self._session.execute(
            select(func.coalesce(func.sum(Debt.amount_rub), 0)).where(
                Debt.user_id == user_id,
                Debt.status.in_(statuses),
            )
        )
        return Decimal(str(result.scalar_one()))

    async def total_active_rub(self, user_id: int) -> Decimal:
        return await self.total_open_rub(user_id)

    async def mark_paid(self, debt: Debt) -> bool:
        """Atomically close an open debt; stale buttons cannot revive/overwrite it."""
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.user_id == debt.user_id,
                Debt.status.in_(
                    [
                        DebtStatus.ACTIVE.value,
                        DebtStatus.NEEDS_REVIEW.value,
                    ]
                ),
            )
            .values(
                status=DebtStatus.PAID.value,
                paid_at=datetime.now(timezone.utc),
                review_remind_at=None,
            )
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def mark_payment_reported(
        self,
        debt: Debt,
        *,
        payer_telegram_id: int,
    ) -> bool:
        """Atomically accept the first report from the bound payer."""
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.status == DebtStatus.ACTIVE.value,
                Debt.payer_telegram_id == payer_telegram_id,
            )
            .values(
                status=DebtStatus.NEEDS_REVIEW.value,
                payment_reported_at=datetime.now(timezone.utc),
                review_remind_at=None,
            )
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def reopen_awaiting(self, debt: Debt) -> bool:
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.user_id == debt.user_id,
                Debt.status == DebtStatus.NEEDS_REVIEW.value,
            )
            .values(
                status=DebtStatus.ACTIVE.value,
                payment_reported_at=None,
                review_remind_at=None,
            )
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def schedule_review_reminder(self, debt: Debt, *, hours: int = 24) -> bool:
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.user_id == debt.user_id,
                Debt.status == DebtStatus.NEEDS_REVIEW.value,
            )
            .values(review_remind_at=datetime.now(timezone.utc) + timedelta(hours=hours))
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def list_due_review_reminders(self, *, now: datetime | None = None) -> list[Debt]:
        moment = now or datetime.now(timezone.utc)
        result = await self._session.execute(
            select(Debt)
            .options(
                selectinload(Debt.friend),
                selectinload(Debt.transaction),
                selectinload(Debt.user),
            )
            .where(
                Debt.status == DebtStatus.NEEDS_REVIEW.value,
                Debt.review_remind_at.is_not(None),
                Debt.review_remind_at <= moment,
            )
        )
        return list(result.scalars().all())

    async def list_stale_needs_review(self, *, older_than: datetime) -> list[Debt]:
        """Debts in needs_review with no pending remind, reported before ``older_than``."""
        result = await self._session.execute(
            select(Debt)
            .options(
                selectinload(Debt.friend),
                selectinload(Debt.transaction),
                selectinload(Debt.user),
            )
            .where(
                Debt.status == DebtStatus.NEEDS_REVIEW.value,
                Debt.review_remind_at.is_(None),
                or_(
                    Debt.payment_reported_at <= older_than,
                    Debt.payment_reported_at.is_(None),
                ),
            )
        )
        rows = list(result.scalars().all())
        # Keep only those with payment_reported_at set and old enough
        return [
            d
            for d in rows
            if d.payment_reported_at is not None and d.payment_reported_at <= older_than
        ]

    async def cancel(self, debt: Debt) -> bool:
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.user_id == debt.user_id,
                Debt.status == DebtStatus.ACTIVE.value,
            )
            .values(status=DebtStatus.CANCELLED.value, review_remind_at=None)
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def update_amount(self, debt: Debt, amount: Decimal) -> bool:
        result = await self._session.execute(
            update(Debt)
            .where(
                Debt.id == debt.id,
                Debt.user_id == debt.user_id,
                Debt.status == DebtStatus.ACTIVE.value,
            )
            .values(amount_rub=amount)
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def delete_open_for_transaction(self, transaction_id: int) -> int:
        statuses = [s.value for s in OPEN_DEBT_STATUSES]
        result = await self._session.execute(
            select(Debt).where(
                Debt.transaction_id == transaction_id,
                Debt.status.in_(statuses),
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self._session.delete(row)
        await self._session.flush()
        return len(rows)

    async def delete_active_for_transaction(self, transaction_id: int) -> int:
        return await self.delete_open_for_transaction(transaction_id)

    async def delete_all_for_transaction(self, transaction_id: int) -> int:
        result = await self._session.execute(
            select(Debt).where(Debt.transaction_id == transaction_id)
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self._session.delete(row)
        await self._session.flush()
        return len(rows)
