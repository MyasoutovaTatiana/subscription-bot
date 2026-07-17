"""Charge confirmation and post-charge editing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BillingType, ConversionMode, DebtStatus, SplitMode, TransactionType
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.repositories.debts import DebtRepository
from app.repositories.friends import FriendRepository
from app.repositories.payment_methods import PaymentMethodRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.repositories.transactions import TransactionRepository
from app.services.billing_dates import calculate_next_charge_date
from app.services.currency import CurrencyConverter
from app.services.debt_calculator import calculate_split
from app.utils.money import MoneyError, ZERO, quantize_money


CHARGE_DATA_UNAVAILABLE_MESSAGE = (
    "Данные подписки изменились или недоступны. Проверьте способ оплаты и участников."
)


class ChargeDataUnavailableError(LookupError):
    """A subscription or one of its owner-scoped relations is unavailable."""

    def __init__(self) -> None:
        super().__init__(CHARGE_DATA_UNAVAILABLE_MESSAGE)


class ChargeService:
    """Confirm subscription charge: transaction, debts, next date; edit after save."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tx = TransactionRepository(session)
        self._debts = DebtRepository(session)
        self._subs = SubscriptionRepository(session)
        self._friends = FriendRepository(session)
        self._payment_methods = PaymentMethodRepository(session)
        self._fx = CurrencyConverter(session)

    async def confirm_charged(
        self,
        subscription: Subscription,
        *,
        user_id: int,
        charge_date: date | None = None,
        actual_rub_amount: Decimal | None = None,
    ):
        subscription = await self._validated_owned_subscription(subscription, user_id)

        if subscription.amount <= 0:
            raise MoneyError("Сумма подписки должна быть больше нуля")

        when = charge_date or subscription.next_charge_date or date.today()
        conv = await self._fx.convert_to_rub(
            Decimal(subscription.amount), subscription.currency, when
        )
        estimated = conv.rub_amount
        actual = quantize_money(actual_rub_amount) if actual_rub_amount is not None else None

        tx = await self._tx.create(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            transaction_type=TransactionType.SUBSCRIPTION.value,
            name=subscription.name,
            category=subscription.category,
            original_amount=subscription.amount,
            original_currency=subscription.currency,
            exchange_rate=conv.unit_rate_rub,
            exchange_rate_date=conv.rate_date,
            estimated_rub_amount=estimated,
            actual_rub_amount=actual,
            is_rate_estimated=actual is None,
            conversion_mode=(
                ConversionMode.CBR.value if actual is None else ConversionMode.ACTUAL_RUB.value
            ),
            transaction_date=when,
            payment_method_id=subscription.payment_method_id,
            split_mode=subscription.split_mode,
            include_owner_in_split=subscription.include_owner_in_split,
        )

        await self._rebuild_splits_and_debts(tx, subscription)

        next_date = calculate_next_charge_date(
            billing_type=subscription.billing_type,
            current_charge_date=when,
            billing_day=subscription.billing_day,
            billing_interval=subscription.billing_interval,
        )
        subscription.next_charge_date = next_date
        await self._subs.save(subscription)

        return tx, next_date, estimated, actual

    async def get_for_user(self, transaction_id: int, user_id: int) -> Transaction | None:
        return await self._tx.get_for_user(transaction_id, user_id)

    @staticmethod
    def effective_rub(tx: Transaction) -> Decimal:
        if tx.actual_rub_amount is not None:
            return Decimal(tx.actual_rub_amount)
        return Decimal(tx.estimated_rub_amount)

    async def update_actual_rub(
        self,
        tx: Transaction,
        amount: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Set fact ₽ amount; recalculate friend debts. Returns (was, now)."""
        subscription = await self._subscription_for(tx)
        await self._validate_rebuild_links(tx, subscription)

        was = self.effective_rub(tx)
        now = quantize_money(amount)
        if now <= ZERO:
            raise MoneyError("Сумма должна быть больше нуля")
        tx.actual_rub_amount = now
        tx.is_rate_estimated = False
        tx.conversion_mode = ConversionMode.ACTUAL_RUB.value
        await self._tx.save(tx)
        await self._rebuild_splits_and_debts(tx, subscription)
        return was, now

    async def update_charge_date(
        self,
        tx: Transaction,
        new_date: date,
    ) -> date | None:
        """
        Change charge date and recompute subscription.next_charge_date from it.
        Also refresh CBR estimate for the new date when fact is not set.
        """
        sub = await self._subscription_for(tx)
        if tx.actual_rub_amount is None:
            await self._validate_rebuild_links(tx, sub)

        tx.transaction_date = new_date
        if sub is None:
            await self._tx.save(tx)
            return None

        if tx.actual_rub_amount is None and tx.original_currency != "RUB":
            try:
                conv = await self._fx.convert_to_rub(
                    Decimal(tx.original_amount),
                    tx.original_currency,
                    new_date,
                )
                tx.exchange_rate = conv.unit_rate_rub
                tx.exchange_rate_date = conv.rate_date
                tx.estimated_rub_amount = conv.rub_amount
                tx.conversion_mode = ConversionMode.CBR.value
                tx.is_rate_estimated = True
            except Exception:  # noqa: BLE001
                pass

        next_date = calculate_next_charge_date(
            billing_type=sub.billing_type,
            current_charge_date=new_date,
            billing_day=new_date.day,
            billing_interval=sub.billing_interval,
        )
        sub.next_charge_date = next_date
        if BillingType(sub.billing_type) == BillingType.MONTHLY:
            sub.billing_day = new_date.day
        await self._subs.save(sub)
        await self._tx.save(tx)
        if tx.actual_rub_amount is None:
            await self._rebuild_splits_and_debts(tx, sub)
        return next_date

    async def update_rate(
        self,
        tx: Transaction,
        unit_rate_rub: Decimal,
    ) -> Decimal:
        """Set manual unit rate (₽ for 1 unit of original currency); update estimate."""
        if unit_rate_rub <= ZERO:
            raise MoneyError("Курс должен быть больше нуля")
        subscription = None
        if tx.actual_rub_amount is None:
            subscription = await self._subscription_for(tx)
            await self._validate_rebuild_links(tx, subscription)

        tx.exchange_rate = unit_rate_rub
        tx.exchange_rate_date = tx.transaction_date
        estimated = quantize_money(Decimal(tx.original_amount) * unit_rate_rub)
        tx.estimated_rub_amount = estimated
        tx.conversion_mode = ConversionMode.MANUAL_RATE.value
        if tx.actual_rub_amount is None:
            tx.is_rate_estimated = True
        await self._tx.save(tx)
        if tx.actual_rub_amount is None:
            await self._rebuild_splits_and_debts(tx, subscription)
        return estimated

    async def recalculate_debts(self, tx: Transaction) -> None:
        await self._rebuild_splits_and_debts(tx, await self._subscription_for(tx))

    async def undo_charge(self, tx: Transaction) -> Subscription | None:
        """
        Cancel charge: delete transaction + debts, restore subscription
        to awaiting the same charge date.
        """
        sub = await self._subscription_for(tx)
        charge_day = tx.transaction_date
        await self._debts.delete_all_for_transaction(tx.id)
        await self._tx.clear_splits(tx)
        await self._tx.delete(tx)
        if sub is not None:
            sub.next_charge_date = charge_day
            if sub.billing_day is None:
                sub.billing_day = charge_day.day
            await self._subs.save(sub)
        return sub

    async def delete_charge(self, tx: Transaction) -> Subscription | None:
        """Delete charge from history; keep next_charge_date as already advanced."""
        sub = await self._subscription_for(tx)
        await self._debts.delete_all_for_transaction(tx.id)
        await self._tx.clear_splits(tx)
        await self._tx.delete(tx)
        return sub

    async def _subscription_for(self, tx: Transaction) -> Subscription | None:
        if tx.subscription_id is None:
            return None
        return await self._subs.get_for_user(tx.subscription_id, tx.user_id)

    async def _rebuild_splits_and_debts(
        self,
        tx: Transaction,
        subscription: Subscription | None,
    ) -> None:
        friend_ids = self._friend_ids(tx, subscription)
        await self._validate_friend_ids(friend_ids, tx.user_id)

        await self._tx.clear_splits(tx)
        await self._debts.delete_active_for_transaction(tx.id)

        if not friend_ids:
            self._session.expire(tx, ["debts", "splits"])
            return

        rub_for_debts = self.effective_rub(tx)
        mode = (
            (subscription.split_mode if subscription else None)
            or tx.split_mode
            or SplitMode.EQUAL.value
        )
        include_owner = (
            subscription.include_owner_in_split
            if subscription is not None
            else tx.include_owner_in_split
        )
        shares = calculate_split(
            mode,
            rub_for_debts,
            friend_ids=friend_ids,
            include_owner=include_owner,
        )
        is_estimated = tx.actual_rub_amount is None
        for share in shares:
            await self._tx.add_split(
                transaction_id=tx.id,
                friend_id=share.friend_id,
                is_owner=share.is_owner,
                amount_rub=share.amount_rub,
                share_value=share.share_value,
            )
            if share.is_owner or share.friend_id is None:
                continue
            await self._debts.create(
                user_id=tx.user_id,
                transaction_id=tx.id,
                friend_id=share.friend_id,
                amount_rub=share.amount_rub,
                is_estimated=is_estimated,
                status=DebtStatus.ACTIVE.value,
            )
        self._session.expire(tx, ["debts", "splits"])

    async def _validated_owned_subscription(
        self,
        subscription: Subscription,
        user_id: int,
    ) -> Subscription:
        if subscription.user_id != user_id:
            raise ChargeDataUnavailableError()
        owned = await self._subs.get_for_user(subscription.id, user_id)
        if owned is None:
            raise ChargeDataUnavailableError()
        await self._validate_subscription_links(owned)
        return owned

    async def _validate_subscription_links(self, subscription: Subscription) -> None:
        if subscription.payment_method_id is not None:
            method = await self._payment_methods.get_for_user(
                subscription.payment_method_id,
                subscription.user_id,
            )
            if method is None:
                raise ChargeDataUnavailableError()
        await self._validate_friend_ids(
            [participant.friend_id for participant in subscription.participants],
            subscription.user_id,
        )

    async def _validate_rebuild_links(
        self,
        tx: Transaction,
        subscription: Subscription | None,
    ) -> None:
        friend_ids = self._friend_ids(tx, subscription)
        await self._validate_friend_ids(friend_ids, tx.user_id)

    async def _validate_friend_ids(self, friend_ids: list[int], user_id: int) -> None:
        requested_ids = set(friend_ids)
        if len(requested_ids) != len(friend_ids):
            raise ChargeDataUnavailableError()
        friends = await self._friends.list_by_ids_for_user(requested_ids, user_id)
        if {friend.id for friend in friends} != requested_ids:
            raise ChargeDataUnavailableError()

    @staticmethod
    def _friend_ids(tx: Transaction, subscription: Subscription | None) -> list[int]:
        if subscription is not None and subscription.participants:
            return [p.friend_id for p in subscription.participants]
        # Avoid lazy-load in async context — only use already-loaded collections.
        ids: list[int] = []
        debts = tx.__dict__.get("debts")
        if debts:
            for debt in debts:
                if debt.status in {
                    DebtStatus.ACTIVE.value,
                    DebtStatus.NEEDS_REVIEW.value,
                } and debt.friend_id not in ids:
                    ids.append(debt.friend_id)
        if ids:
            return ids
        splits = tx.__dict__.get("splits")
        if splits:
            for split in splits:
                if not split.is_owner and split.friend_id and split.friend_id not in ids:
                    ids.append(split.friend_id)
        return ids
