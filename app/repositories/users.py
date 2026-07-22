"""User repository."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.debt import Debt
from app.models.enums import DEFAULT_REMINDER_OFFSETS
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription, SubscriptionParticipant
from app.models.transaction import Transaction, TransactionSplit
from app.models.user import User


class UserDataUnavailableError(LookupError):
    """User row is missing or does not match the current actor."""


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        with self._session.no_autoflush:
            result = await self._session.execute(
                select(User)
                .where(User.id == user_id)
                .execution_options(populate_existing=True)
            )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
        timezone: str = "Europe/Moscow",
        default_reminder_time: str = "10:00",
    ) -> User:
        user = User(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            username=username,
            first_name=first_name,
            timezone=timezone,
            default_reminder_time=default_reminder_time,
            default_reminder_offsets=list(DEFAULT_REMINDER_OFFSETS),
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_profile(
        self,
        user: User,
        *,
        user_id: int,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        owned = await self._validated_user(user, user_id)
        owned.telegram_chat_id = telegram_chat_id
        owned.username = username
        owned.first_name = first_name
        await self._session.flush()
        return owned

    async def wipe_user(self, user: User, *, user_id: int) -> None:
        """Delete the user row and every record they own, in one flush.

        Children are removed before parents so the result is correct even with
        SQLite foreign-key enforcement off and without relying on DB cascade.
        Does NOT commit — the caller owns the transaction boundary.

        Before removing Friend / PaymentMethod / User, detaches legacy
        cross-user references that could exist from before owner-checks
        (other users' rows pointing at this user's friends or payment methods).
        Direct Telegram bindings on other users' debts (``payer_telegram_id``)
        are cleared; other users' Subscription / Transaction rows are kept.
        """
        user = await self._validated_user(user, user_id)
        telegram_user_id = user.telegram_user_id

        owned_friend_ids = select(Friend.id).where(Friend.user_id == user_id)
        owned_payment_method_ids = select(PaymentMethod.id).where(
            PaymentMethod.user_id == user_id
        )

        # --- Detach legacy cross-user FKs (before deleting Friend / PaymentMethod) ---

        # PaymentMethod A on B's Subscription / Transaction (nullable → NULL).
        await self._session.execute(
            update(Subscription)
            .where(Subscription.payment_method_id.in_(owned_payment_method_ids))
            .values(payment_method_id=None)
        )
        await self._session.execute(
            update(Transaction)
            .where(Transaction.payment_method_id.in_(owned_payment_method_ids))
            .values(payment_method_id=None)
        )

        # Friend A on B's SubscriptionParticipant (friend_id NOT NULL → drop association only).
        await self._session.execute(
            delete(SubscriptionParticipant).where(
                SubscriptionParticipant.friend_id.in_(owned_friend_ids)
            )
        )

        # Friend A on B's TransactionSplit: delete the bad split only.
        # Do not leave friend_id=NULL + is_owner=False — consumers treat
        # friend_id is None as the owner's share, not a deleted participant.
        await self._session.execute(
            delete(TransactionSplit).where(
                TransactionSplit.friend_id.in_(owned_friend_ids)
            )
        )

        # Friend A on B's Debt (friend_id NOT NULL → delete debt row only; keep Transaction B).
        # Matches schema ondelete=CASCADE on debts.friend_id without relying on SQLite FK.
        await self._session.execute(
            delete(Debt).where(Debt.friend_id.in_(owned_friend_ids))
        )

        # Direct Telegram id of A on other users' debts.
        await self._session.execute(
            update(Debt)
            .where(Debt.payer_telegram_id == telegram_user_id)
            .values(payer_telegram_id=None)
        )

        # --- Owned data of A (grandchildren → children → user) ---

        await self._session.execute(
            delete(TransactionSplit).where(
                TransactionSplit.transaction_id.in_(
                    select(Transaction.id).where(Transaction.user_id == user_id)
                )
            )
        )
        await self._session.execute(
            delete(SubscriptionParticipant).where(
                SubscriptionParticipant.subscription_id.in_(
                    select(Subscription.id).where(Subscription.user_id == user_id)
                )
            )
        )

        await self._session.execute(
            delete(ReminderDelivery).where(ReminderDelivery.user_id == user_id)
        )
        await self._session.execute(delete(Debt).where(Debt.user_id == user_id))
        await self._session.execute(delete(Transaction).where(Transaction.user_id == user_id))
        await self._session.execute(delete(Subscription).where(Subscription.user_id == user_id))
        await self._session.execute(delete(PaymentMethod).where(PaymentMethod.user_id == user_id))
        await self._session.execute(delete(Friend).where(Friend.user_id == user_id))

        await self._session.execute(delete(User).where(User.id == user_id))
        await self._session.flush()

    async def _validated_user(self, user: User, user_id: int) -> User:
        if user.id != user_id:
            raise UserDataUnavailableError()
        owned = await self.get_by_id(user_id)
        if owned is None:
            raise UserDataUnavailableError()
        return owned
