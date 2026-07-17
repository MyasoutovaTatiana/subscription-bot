"""Transaction / one-time payment service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConversionMode, DebtStatus, SplitMode, TransactionType
from app.models.transaction import Transaction
from app.repositories.debts import DebtRepository
from app.repositories.friends import FriendRepository, FriendsUnavailableError
from app.repositories.payment_methods import (
    PaymentMethodRepository,
    PaymentMethodUnavailableError,
)
from app.repositories.transactions import TransactionRepository
from app.services.currency import CurrencyConverter
from app.services.debt_calculator import ParticipantShare, calculate_split
from app.utils.money import MoneyError, quantize_money


@dataclass(slots=True)
class CreateOneTimePaymentDTO:
    user_id: int
    name: str
    category: str
    original_amount: Decimal
    original_currency: str
    transaction_date: date
    payment_method_id: int | None
    conversion_mode: str
    manual_rate: Decimal | None = None
    actual_rub_amount: Decimal | None = None
    include_owner_in_split: bool = True
    split_mode: str | None = None
    friend_ids: list[int] = field(default_factory=list)
    percent_map: dict[int | None, Decimal] | None = None  # friend_id/None(owner) -> %
    fixed_map: dict[int | None, Decimal] | None = None
    notes: str | None = None


class TransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tx_repo = TransactionRepository(session)
        self._debt_repo = DebtRepository(session)
        self._converter = CurrencyConverter(session)

    async def create_one_time(self, dto: CreateOneTimePaymentDTO) -> Transaction:
        if dto.original_amount <= 0:
            raise MoneyError("Нельзя создать платёж с нулевой или отрицательной суммой")

        friend_ids = list(dict.fromkeys(dto.friend_ids))
        requested_friend_ids = set(friend_ids)
        friends = await FriendRepository(self._session).list_by_ids_for_user(
            requested_friend_ids,
            dto.user_id,
        )
        if {friend.id for friend in friends} != requested_friend_ids:
            raise FriendsUnavailableError()

        if dto.payment_method_id is not None:
            method = await PaymentMethodRepository(self._session).get_active_for_user(
                dto.payment_method_id,
                dto.user_id,
            )
            if method is None:
                raise PaymentMethodUnavailableError()

        exchange_rate: Decimal | None
        exchange_rate_date: date | None
        estimated: Decimal
        actual = dto.actual_rub_amount
        is_rate_estimated = True
        mode = ConversionMode(dto.conversion_mode)

        if mode == ConversionMode.ACTUAL_RUB:
            if actual is None or actual <= 0:
                raise MoneyError("Укажи фактическую сумму в рублях больше нуля")
            estimated = quantize_money(actual)
            exchange_rate = quantize_money(actual / dto.original_amount)
            exchange_rate_date = dto.transaction_date
            is_rate_estimated = False
        elif mode == ConversionMode.MANUAL_RATE:
            if dto.manual_rate is None or dto.manual_rate <= 0:
                raise MoneyError("Укажи курс больше нуля")
            exchange_rate = dto.manual_rate
            exchange_rate_date = dto.transaction_date
            estimated = quantize_money(dto.original_amount * dto.manual_rate)
        else:
            conv = await self._converter.convert_to_rub(
                dto.original_amount,
                dto.original_currency,
                dto.transaction_date,
            )
            exchange_rate = conv.unit_rate_rub
            exchange_rate_date = conv.rate_date
            estimated = conv.rub_amount

        rub_for_split = actual if actual is not None else estimated

        tx = await self._tx_repo.create(
            user_id=dto.user_id,
            subscription_id=None,
            transaction_type=TransactionType.ONE_TIME.value,
            name=dto.name.strip(),
            category=dto.category,
            original_amount=dto.original_amount,
            original_currency=dto.original_currency.upper(),
            exchange_rate=exchange_rate,
            exchange_rate_date=exchange_rate_date,
            estimated_rub_amount=estimated,
            actual_rub_amount=actual,
            is_rate_estimated=is_rate_estimated,
            conversion_mode=mode.value,
            transaction_date=dto.transaction_date,
            payment_method_id=dto.payment_method_id,
            split_mode=dto.split_mode,
            include_owner_in_split=dto.include_owner_in_split,
            notes=dto.notes,
        )

        if dto.split_mode and (friend_ids or dto.include_owner_in_split):
            shares = self._build_shares(dto, rub_for_split, friend_ids=friend_ids)
            await self._persist_shares(tx, shares, dto, is_estimated=actual is None)

        loaded = await self._tx_repo.get_for_user(tx.id, dto.user_id)
        assert loaded is not None
        return loaded

    def _build_shares(
        self,
        dto: CreateOneTimePaymentDTO,
        total_rub: Decimal,
        *,
        friend_ids: list[int],
    ) -> list[ParticipantShare]:
        mode = SplitMode(dto.split_mode or SplitMode.EQUAL.value)
        if mode == SplitMode.EQUAL:
            return calculate_split(
                mode,
                total_rub,
                friend_ids=friend_ids,
                include_owner=dto.include_owner_in_split,
            )
        if mode == SplitMode.PERCENT:
            percents: list[tuple[int | None, bool, Decimal]] = []
            mapping = dto.percent_map or {}
            if dto.include_owner_in_split:
                percents.append((None, True, mapping.get(None, Decimal("0"))))
            for fid in friend_ids:
                percents.append((fid, False, mapping.get(fid, Decimal("0"))))
            return calculate_split(mode, total_rub, percents=percents)
        if mode == SplitMode.FIXED:
            fixed: list[tuple[int | None, bool, Decimal]] = []
            mapping = dto.fixed_map or {}
            if dto.include_owner_in_split:
                fixed.append((None, True, mapping.get(None, Decimal("0"))))
            for fid in friend_ids:
                fixed.append((fid, False, mapping.get(fid, Decimal("0"))))
            return calculate_split(mode, total_rub, fixed=fixed)
        raise MoneyError("Такое деление пока недоступно")

    async def _persist_shares(
        self,
        tx: Transaction,
        shares: list[ParticipantShare],
        dto: CreateOneTimePaymentDTO,
        *,
        is_estimated: bool,
    ) -> None:
        for share in shares:
            await self._tx_repo.add_split(
                transaction_id=tx.id,
                friend_id=share.friend_id,
                is_owner=share.is_owner,
                amount_rub=share.amount_rub,
                share_value=share.share_value,
            )
            if share.is_owner or share.friend_id is None:
                continue
            await self._debt_repo.create(
                user_id=dto.user_id,
                transaction_id=tx.id,
                friend_id=share.friend_id,
                amount_rub=share.amount_rub,
                original_share_amount=None,
                original_share_currency=None,
                is_estimated=is_estimated,
                status=DebtStatus.ACTIVE.value,
            )
