"""Split / debt amount calculator (pure functions)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import SplitMode
from app.utils.money import MoneyError, quantize_money, ZERO


@dataclass(frozen=True, slots=True)
class ParticipantShare:
    """Share assignment before persistence."""

    friend_id: int | None  # None + is_owner => owner
    is_owner: bool
    amount_rub: Decimal
    share_value: Decimal | None = None


def split_equal(
    total_rub: Decimal,
    *,
    friend_ids: list[int],
    include_owner: bool,
) -> list[ParticipantShare]:
    """
    Split ``total_rub`` equally.

    Remainder kopecks after rounding go to the owner if included,
    otherwise to the last friend.
    """
    if total_rub <= ZERO:
        raise MoneyError("Нельзя создать платёж с нулевой или отрицательной суммой")

    participants: list[tuple[int | None, bool]] = []
    if include_owner:
        participants.append((None, True))
    for fid in friend_ids:
        participants.append((fid, False))

    n = len(participants)
    if n == 0:
        raise MoneyError("Нужен хотя бы один участник деления")

    total = quantize_money(total_rub)
    base = quantize_money(total / n)
    shares = [base] * n
    remainder = total - (base * n)
    # Assign leftover kopecks one-by-one to owner (index 0 if present) else last.
    target_index = 0 if include_owner else (n - 1)
    # remainder is multiple of 0.01
    step = Decimal("0.01") if remainder >= ZERO else Decimal("-0.01")
    left = remainder
    idx = target_index
    while left != ZERO:
        shares[idx] = quantize_money(shares[idx] + step)
        left = quantize_money(left - step)
        if not include_owner:
            # keep sticking to last participant
            idx = n - 1

    result = [
        ParticipantShare(friend_id=fid, is_owner=is_owner, amount_rub=shares[i])
        for i, (fid, is_owner) in enumerate(participants)
    ]
    assert sum((s.amount_rub for s in result), ZERO) == total
    return result


def split_percent(
    total_rub: Decimal,
    *,
    percents: list[tuple[int | None, bool, Decimal]],
) -> list[ParticipantShare]:
    """
    ``percents``: list of (friend_id, is_owner, percent 0-100).

    Sum of percents must be exactly 100. Remainder kopecks → owner if present else last.
    """
    if total_rub <= ZERO:
        raise MoneyError("Нельзя создать платёж с нулевой или отрицательной суммой")
    if not percents:
        raise MoneyError("Укажи проценты для участников")

    total_pct = sum((p for _, _, p in percents), ZERO)
    if total_pct != Decimal("100"):
        raise MoneyError(f"Сумма процентов должна быть 100%, сейчас {total_pct}%")

    total = quantize_money(total_rub)
    raw_shares: list[Decimal] = []
    for _, _, pct in percents:
        if pct < ZERO:
            raise MoneyError("Процент не может быть отрицательным")
        raw_shares.append(quantize_money(total * pct / Decimal("100")))

    remainder = total - sum(raw_shares, ZERO)
    # Prefer owner index
    owner_idx = next((i for i, (_, is_owner, _) in enumerate(percents) if is_owner), len(percents) - 1)
    raw_shares[owner_idx] = quantize_money(raw_shares[owner_idx] + remainder)

    return [
        ParticipantShare(
            friend_id=fid,
            is_owner=is_owner,
            amount_rub=raw_shares[i],
            share_value=pct,
        )
        for i, (fid, is_owner, pct) in enumerate(percents)
    ]


def split_fixed(
    total_rub: Decimal,
    *,
    fixed: list[tuple[int | None, bool, Decimal]],
) -> list[ParticipantShare]:
    """Fixed RUB amounts must sum exactly to total."""
    if total_rub <= ZERO:
        raise MoneyError("Нельзя создать платёж с нулевой или отрицательной суммой")
    total = quantize_money(total_rub)
    amounts = []
    for fid, is_owner, amount in fixed:
        if amount < ZERO:
            raise MoneyError("Доля не может быть отрицательной")
        amounts.append((fid, is_owner, quantize_money(amount)))
    summed = sum((a for _, _, a in amounts), ZERO)
    if summed != total:
        raise MoneyError(
            f"Сумма фиксированных долей ({summed} ₽) должна совпадать с общей суммой ({total} ₽)"
        )
    return [
        ParticipantShare(friend_id=fid, is_owner=is_owner, amount_rub=amount, share_value=amount)
        for fid, is_owner, amount in amounts
    ]


def split_custom_shares(
    total_rub: Decimal,
    *,
    shares: list[tuple[int | None, bool, Decimal]],
) -> list[ParticipantShare]:
    """
    Custom relative shares (weights). Amounts proportional to weights.
    Remainder → owner if present else last.
    """
    if total_rub <= ZERO:
        raise MoneyError("Нельзя создать платёж с нулевой или отрицательной суммой")
    weights = [w for _, _, w in shares]
    if any(w <= ZERO for w in weights):
        raise MoneyError("Доли должны быть больше нуля")
    weight_sum = sum(weights, ZERO)
    total = quantize_money(total_rub)
    raw = [quantize_money(total * (w / weight_sum)) for w in weights]
    remainder = total - sum(raw, ZERO)
    owner_idx = next((i for i, (_, is_owner, _) in enumerate(shares) if is_owner), len(shares) - 1)
    raw[owner_idx] = quantize_money(raw[owner_idx] + remainder)
    return [
        ParticipantShare(friend_id=fid, is_owner=is_owner, amount_rub=raw[i], share_value=w)
        for i, (fid, is_owner, w) in enumerate(shares)
    ]


def calculate_split(
    mode: SplitMode | str,
    total_rub: Decimal,
    *,
    friend_ids: list[int] | None = None,
    include_owner: bool = True,
    percents: list[tuple[int | None, bool, Decimal]] | None = None,
    fixed: list[tuple[int | None, bool, Decimal]] | None = None,
    custom_shares: list[tuple[int | None, bool, Decimal]] | None = None,
) -> list[ParticipantShare]:
    mode = SplitMode(mode)
    if mode == SplitMode.EQUAL:
        return split_equal(total_rub, friend_ids=friend_ids or [], include_owner=include_owner)
    if mode == SplitMode.PERCENT:
        return split_percent(total_rub, percents=percents or [])
    if mode == SplitMode.FIXED:
        return split_fixed(total_rub, fixed=fixed or [])
    if mode == SplitMode.CUSTOM_SHARES:
        return split_custom_shares(total_rub, shares=custom_shares or [])
    raise ValueError(f"Unknown split mode: {mode}")
