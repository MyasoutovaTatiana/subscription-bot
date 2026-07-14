"""Transaction repository."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **kwargs) -> Transaction:
        row = Transaction(**kwargs)
        self._session.add(row)
        await self._session.flush()
        return row

    async def add_split(self, **kwargs) -> TransactionSplit:
        row = TransactionSplit(**kwargs)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_for_user(self, transaction_id: int, user_id: int) -> Transaction | None:
        result = await self._session.execute(
            select(Transaction)
            .options(
                selectinload(Transaction.splits),
                selectinload(Transaction.debts),
                selectinload(Transaction.payment_method),
                selectinload(Transaction.subscription).selectinload(Subscription.participants).selectinload(
                    SubscriptionParticipant.friend
                ),
                selectinload(Transaction.subscription).selectinload(Subscription.payment_method),
            )
            .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_actual_rub(self, tx: Transaction, amount: Decimal) -> Transaction:
        tx.actual_rub_amount = amount
        await self._session.flush()
        return tx

    async def save(self, tx: Transaction) -> Transaction:
        await self._session.flush()
        return tx

    async def clear_splits(self, tx: Transaction) -> None:
        await self._session.execute(
            delete(TransactionSplit).where(TransactionSplit.transaction_id == tx.id)
        )
        await self._session.flush()
        loaded = tx.__dict__.get("splits")
        if loaded is not None:
            loaded.clear()

    async def delete(self, tx: Transaction) -> None:
        await self._session.delete(tx)
        await self._session.flush()
