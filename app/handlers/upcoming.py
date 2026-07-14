"""Upcoming charges view."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.main_menu import BTN_UPCOMING
from app.models.enums import CurrencyCode
from app.models.user import User
from app.repositories.subscriptions import SubscriptionRepository
from app.services.currency import CurrencyConverter
from app.ui.presentation import format_rub_estimate, screen
from app.utils.callback_data import MenuCb
from app.utils.dates import format_charge_when
from app.utils.money import format_money
from app.utils.telegram import escape_html

router = Router(name="upcoming")


def upcoming_period_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="7 дней", callback_data=MenuCb(action="up", value="7").pack())
    b.button(text="30 дней", callback_data=MenuCb(action="up", value="30").pack())
    b.button(text="Все", callback_data=MenuCb(action="up", value="all").pack())
    b.adjust(3)
    return b.as_markup()


@router.message(F.text == BTN_UPCOMING)
@router.message(Command("upcoming"))
async def upcoming_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        screen("📅 <b>Списания</b>", "Выбери период"),
        reply_markup=upcoming_period_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(MenuCb.filter(F.action == "up"))
async def upcoming_show(
    callback: CallbackQuery,
    callback_data: MenuCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    today = date.today()
    until: date | None
    title: str
    if callback_data.value == "7":
        until = today + timedelta(days=7)
        title = "Ближайшие 7 дней"
    elif callback_data.value == "30":
        until = today + timedelta(days=30)
        title = "Ближайшие 30 дней"
    else:
        until = None
        title = "Все активные"

    repo = SubscriptionRepository(session)
    subs = await repo.list_upcoming(db_user.id, until=until)
    if not subs:
        await callback.message.edit_text(
            screen(f"📅 <b>{title}</b>", "Списаний нет"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    converter = CurrencyConverter(session)
    by_date: dict[date, list] = defaultdict(list)
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_rub_est = Decimal("0")
    has_missing_fx = False

    for sub in subs:
        assert sub.next_charge_date is not None
        by_date[sub.next_charge_date].append(sub)
        totals[sub.currency] += Decimal(sub.amount)
        try:
            conv = await converter.convert_to_rub(
                Decimal(sub.amount), sub.currency, sub.next_charge_date
            )
            rub = conv.rub_amount
        except Exception:  # noqa: BLE001
            rub = Decimal(sub.amount) if sub.currency == CurrencyCode.RUB.value else None
            if rub is None:
                has_missing_fx = True
        if rub is not None:
            total_rub_est += rub
            sub._est_rub = rub  # type: ignore[attr-defined]
        else:
            sub._est_rub = None  # type: ignore[attr-defined]

    day_blocks: list[str] = []
    for day in sorted(by_date):
        head = format_charge_when(day, today=today)
        lines = [f"<b>{head.splitlines()[0]}</b> · {head.splitlines()[1]}"]
        for sub in by_date[day]:
            amount = format_money(Decimal(sub.amount), sub.currency)
            est = getattr(sub, "_est_rub", None)
            rub = format_rub_estimate(est, currency=sub.currency)
            if rub and sub.currency != CurrencyCode.RUB.value and est is not None:
                lines.append(f"— {escape_html(sub.name)}\n  {amount}  {rub}")
            else:
                lines.append(f"— {escape_html(sub.name)}\n  {amount}")
        day_blocks.append("\n".join(lines))

    totals_lines = [format_money(amount, cur) for cur, amount in sorted(totals.items())]
    if has_missing_fx:
        totals_lines.append(f"≈ {format_money(total_rub_est, 'RUB')} + не рассчитано")
    else:
        totals_lines.append(f"≈ {format_money(total_rub_est, 'RUB')}")

    text = screen(
        f"📅 <b>{title}</b>",
        *day_blocks,
        "Итого\n" + "\n".join(totals_lines),
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()
