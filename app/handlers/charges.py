"""Handlers for saved charge (transaction) card editing."""

from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import NotNavigationOrCommand
from app.keyboards.main_menu import main_menu_keyboard
from app.keyboards.subscriptions import (
    charge_card_keyboard,
    confirm_charge_action_keyboard,
    subscription_card_keyboard,
)
from app.models.enums import CurrencyCode
from app.models.user import User
from app.services.charge_cards import format_amount_updated, format_charge_card, format_rate_updated
from app.services.charges import ChargeDateConflictError, ChargeService
from app.services.subscription_cards import format_subscription_card
from app.states.subscriptions import EditChargeSG
from app.ui import Copy, human_error, toast_ok
from app.utils.callback_data import TxCb
from app.utils.dates import parse_user_date
from app.utils.money import MoneyError, parse_amount

router = Router(name="charges")


def _next_date(tx) -> object:
    sub = getattr(tx, "subscription", None)
    return sub.next_charge_date if sub is not None else None


def _charge_markup(tx):
    return charge_card_keyboard(
        tx.id,
        subscription_id=tx.subscription_id or 0,
        show_rate=tx.original_currency != CurrencyCode.RUB.value,
    )


async def render_charge_card(
    target: Message,
    tx,
    *,
    edit: bool,
    heading: str | None = None,
) -> None:
    text = format_charge_card(tx, next_charge_date=_next_date(tx), heading=heading)
    markup = _charge_markup(tx)
    if edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(TxCb.filter(F.action == "view"))
async def cb_tx_view(
    callback: CallbackQuery,
    callback_data: TxCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    tx = await ChargeService(session).get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Списание не найдено", show_alert=True)
        return
    await render_charge_card(callback.message, tx, edit=True)
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "amt"))
async def cb_tx_amt(
    callback: CallbackQuery,
    callback_data: TxCb,
    state: FSMContext,
) -> None:
    await state.set_state(EditChargeSG.amount)
    await state.update_data(edit_tid=callback_data.tid)
    await callback.message.answer(
        "Новая фактическая сумма <b>в рублях</b>\nНапример: 1589,32",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "date"))
async def cb_tx_date(
    callback: CallbackQuery,
    callback_data: TxCb,
    state: FSMContext,
) -> None:
    await state.set_state(EditChargeSG.date)
    await state.update_data(edit_tid=callback_data.tid)
    await callback.message.answer("Новая дата списания\nНапример: 14.07.2026")
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "rate"))
async def cb_tx_rate(
    callback: CallbackQuery,
    callback_data: TxCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    tx = await ChargeService(session).get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Списание не найдено", show_alert=True)
        return
    if tx.original_currency == CurrencyCode.RUB.value:
        await callback.answer("Для рублей курс не нужен", show_alert=True)
        return
    await state.set_state(EditChargeSG.rate)
    await state.update_data(edit_tid=callback_data.tid)
    await callback.message.answer(
        f"Курс: сколько ₽ за 1 {tx.original_currency}\nНапример: 92,50",
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "recalc"))
async def cb_tx_recalc(
    callback: CallbackQuery,
    callback_data: TxCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = ChargeService(session)
    tx = await service.get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Списание не найдено", show_alert=True)
        return
    await service.recalculate_debts(tx)
    tx = await service.get_for_user(callback_data.tid, db_user.id)
    await render_charge_card(callback.message, tx, edit=True)
    await callback.answer(Copy.DEBTS_RECALCULATED)


@router.callback_query(TxCb.filter(F.action == "undo"))
async def cb_tx_undo_ask(
    callback: CallbackQuery,
    callback_data: TxCb,
) -> None:
    await callback.message.edit_text(
        "↩️ Отменить списание?\n\n"
        "Транзакция и долги будут удалены.\n"
        f"Подписка вернётся в статус «{Copy.AWAITING_CHARGE}».",
        reply_markup=confirm_charge_action_keyboard(callback_data.tid, action="undo"),
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "del"))
async def cb_tx_del_ask(
    callback: CallbackQuery,
    callback_data: TxCb,
) -> None:
    await callback.message.edit_text(
        "🗑 Удалить списание из истории?\n\n"
        "Дата следующего списания подписки не изменится.",
        reply_markup=confirm_charge_action_keyboard(callback_data.tid, action="del"),
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "undo_yes"))
async def cb_tx_undo_yes(
    callback: CallbackQuery,
    callback_data: TxCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    from app.services.currency import CurrencyConverter

    service = ChargeService(session)
    tx = await service.get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Списание не найдено", show_alert=True)
        return
    sub = await service.undo_charge(tx)
    if sub is None:
        await callback.message.edit_text(f"✅ {Copy.CHARGE_UNDONE}")
        await callback.answer()
        return

    estimated = None
    try:
        if sub.next_charge_date:
            conv = await CurrencyConverter(session).convert_to_rub(
                Decimal(sub.amount), sub.currency, sub.next_charge_date
            )
            estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None

    await callback.message.edit_text(
        format_subscription_card(
            sub,
            estimated_rub=estimated,
            title=f"✅ {Copy.CHARGE_UNDONE}",
        ),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer(Copy.AWAITING_CHARGE)


@router.callback_query(TxCb.filter(F.action == "del_yes"))
async def cb_tx_del_yes(
    callback: CallbackQuery,
    callback_data: TxCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    from app.services.currency import CurrencyConverter

    service = ChargeService(session)
    tx = await service.get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Списание не найдено", show_alert=True)
        return
    sub = await service.delete_charge(tx)
    if sub is None:
        await callback.message.edit_text(f"✅ {Copy.CHARGE_DELETED}")
        await callback.answer()
        return

    estimated = None
    try:
        if sub.next_charge_date:
            conv = await CurrencyConverter(session).convert_to_rub(
                Decimal(sub.amount), sub.currency, sub.next_charge_date
            )
            estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None

    await callback.message.edit_text(
        format_subscription_card(
            sub,
            estimated_rub=estimated,
            title=f"✅ {Copy.CHARGE_DELETED}",
        ),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "back"))
async def cb_tx_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(Copy.OPEN_HOME)
    await callback.answer()


@router.message(EditChargeSG.amount, NotNavigationOrCommand())
async def edit_charge_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    data = await state.get_data()
    tid = int(data.get("edit_tid") or 0)
    service = ChargeService(session)
    tx = await service.get_for_user(tid, db_user.id)
    if tx is None:
        await state.clear()
        await message.answer("Списание не найдено.", reply_markup=main_menu_keyboard())
        return
    try:
        amount = parse_amount(message.text or "")
        was, now = await service.update_actual_rub(tx, amount)
    except (MoneyError, ValueError) as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    await message.answer(format_amount_updated(was=was, now=now), parse_mode="HTML")
    tx = await service.get_for_user(tid, db_user.id)
    await render_charge_card(message, tx, edit=False)


@router.message(EditChargeSG.date, NotNavigationOrCommand())
async def edit_charge_date(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    data = await state.get_data()
    tid = int(data.get("edit_tid") or 0)
    service = ChargeService(session)
    tx = await service.get_for_user(tid, db_user.id)
    if tx is None:
        await state.clear()
        await message.answer("Списание не найдено.", reply_markup=main_menu_keyboard())
        return
    try:
        new_date = parse_user_date((message.text or "").strip())
        await service.update_charge_date(tx, new_date)
    except ChargeDateConflictError as exc:
        await message.answer(str(exc))
        return
    except ValueError as exc:
        await message.answer(str(exc) or "Не понял дату. Пример: 14.07.2026")
        return

    await state.clear()
    await message.answer(toast_ok(Copy.DATE_UPDATED))
    tx = await service.get_for_user(tid, db_user.id)
    await render_charge_card(message, tx, edit=False)


@router.message(EditChargeSG.rate, NotNavigationOrCommand())
async def edit_charge_rate(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    data = await state.get_data()
    tid = int(data.get("edit_tid") or 0)
    service = ChargeService(session)
    tx = await service.get_for_user(tid, db_user.id)
    if tx is None:
        await state.clear()
        await message.answer("Списание не найдено.", reply_markup=main_menu_keyboard())
        return
    try:
        rate = parse_amount(message.text or "")
        estimated = await service.update_rate(tx, rate)
    except (MoneyError, ValueError) as exc:
        await message.answer(human_error(str(exc)))
        return

    await state.clear()
    await message.answer(
        format_rate_updated(
            estimated_rub=estimated,
            rate=rate,
            currency=tx.original_currency,
        ),
        parse_mode="HTML",
    )
    tx = await service.get_for_user(tid, db_user.id)
    await render_charge_card(message, tx, edit=False)
