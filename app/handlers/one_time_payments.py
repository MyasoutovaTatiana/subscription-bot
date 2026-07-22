"""One-time payment FSM handlers."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import NotNavigationOrCommand
from app.keyboards.calendar import calendar_keyboard, ot_currencies_keyboard, payment_date_quick_keyboard
from app.keyboards.main_menu import BTN_ONE_TIME, main_menu_keyboard
from app.keyboards.payments import (
    confirm_payment_keyboard,
    friends_select_keyboard,
    payment_saved_keyboard,
    split_mode_keyboard,
    yes_no_keyboard,
)
from app.keyboards.subscriptions import payment_methods_keyboard
from app.models.enums import ConversionMode, CurrencyCode, SplitMode, SubscriptionCategory
from app.models.user import User
from app.repositories.friends import (
    FRIENDS_UNAVAILABLE_MESSAGE,
    FriendRepository,
    FriendsUnavailableError,
)
from app.repositories.payment_methods import (
    PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
    PaymentMethodRepository,
    PaymentMethodUnavailableError,
)
from app.services.currency import CurrencyConverter
from app.services.transactions import CreateOneTimePaymentDTO, TransactionService
from app.states.payments import OneTimePaymentSG
from app.ui import (
    Copy,
    Icon,
    bullets,
    entity_name,
    field,
    money,
    rate_line,
    screen,
    success_screen,
    title,
)
from app.utils.callback_data import MenuCb, TxCb
from app.utils.dates import format_date_ru_short, parse_user_date
from app.utils.money import MoneyError, parse_amount, quantize_money
from app.utils.telegram import escape_html

router = Router(name="one_time_payments")


def _amount_prompt(*, name: str, currency: str) -> str:
    return screen(
        title(Icon.PAYMENT, "Сумма покупки"),
        field(Icon.HOTEL, "Название", escape_html(name)),
        field(Icon.RATE, "Валюта", currency),
        "Введите сумму покупки.",
    )


async def _go_friends(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.set_state(OneTimePaymentSG.friends)
    await state.update_data(selected_friend_ids=[])
    friends = await FriendRepository(session).list_for_user(db_user.id)
    await message.answer(
        screen(title(Icon.DEBTS, "Кто участвует"), "Можно отметить несколько человек"),
        reply_markup=friends_select_keyboard(friends, set()),
        parse_mode="HTML",
    )


async def _go_payment_method(
    target: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    *,
    edit: bool = False,
) -> None:
    await state.set_state(OneTimePaymentSG.payment_method)
    methods = await PaymentMethodRepository(session).list_active(db_user.id)
    text = screen(title(Icon.CARD, "Карта"), "Выбери способ оплаты")
    kb = payment_methods_keyboard(methods)
    if edit:
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == BTN_ONE_TIME)
@router.message(Command("payment"))
async def start_one_time(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OneTimePaymentSG.name)
    await message.answer(
        screen(title(Icon.PAYMENT, "Разовый платёж"), "Название?\nНапример: Отель в Японии"),
        parse_mode="HTML",
    )


@router.message(OneTimePaymentSG.name, NotNavigationOrCommand())
async def ot_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название.")
        return
    await state.update_data(name=name)
    await state.set_state(OneTimePaymentSG.currency)
    await message.answer(
        screen(title(Icon.RATE, "Валюта"), escape_html(name)),
        reply_markup=ot_currencies_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(OneTimePaymentSG.currency, MenuCb.filter(F.action == "cur"))
async def ot_currency(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(currency=callback_data.value)
    await state.set_state(OneTimePaymentSG.amount)
    await callback.message.edit_text(
        _amount_prompt(name=data["name"], currency=callback_data.value),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(OneTimePaymentSG.amount, NotNavigationOrCommand())
async def ot_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = parse_amount(message.text or "")
    except MoneyError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(amount=str(amount))
    await state.set_state(OneTimePaymentSG.payment_date)
    await message.answer(
        screen(title(Icon.CALENDAR, "Дата"), "Когда была покупка?"),
        reply_markup=payment_date_quick_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(OneTimePaymentSG.payment_date, MenuCb.filter(F.action == "pdate"))
async def ot_date_quick(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    value = callback_data.value
    today = date.today()
    if value == "today":
        await state.update_data(payment_date=today.isoformat())
        await _go_payment_method(callback.message, state, session, db_user, edit=True)
        await callback.answer()
        return
    if value == "yesterday":
        await state.update_data(payment_date=(today - timedelta(days=1)).isoformat())
        await _go_payment_method(callback.message, state, session, db_user, edit=True)
        await callback.answer()
        return
    # pick calendar
    await callback.message.edit_text(
        screen(title(Icon.CALENDAR, "Выбери дату"), "Или напиши дату текстом: 14.07.2026"),
        reply_markup=calendar_keyboard(today.year, today.month, action_prefix="cal"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(OneTimePaymentSG.payment_date, MenuCb.filter(F.action == "cal"))
async def ot_calendar(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    value = callback_data.value
    if value == "noop" or not value:
        await callback.answer()
        return
    if value.startswith("m:"):
        y_str, m_str = value[2:].split("-", 1)
        await callback.message.edit_reply_markup(
            reply_markup=calendar_keyboard(int(y_str), int(m_str), action_prefix="cal"),
        )
        await callback.answer()
        return
    if value.startswith("d:"):
        iso = value[2:]
        await state.update_data(payment_date=iso)
        await _go_payment_method(callback.message, state, session, db_user, edit=True)
        await callback.answer()
        return
    await callback.answer()


@router.message(OneTimePaymentSG.payment_date, NotNavigationOrCommand())
async def ot_date_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    try:
        payment_date = parse_user_date(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(payment_date=payment_date.isoformat())
    await _go_payment_method(message, state, session, db_user)


@router.callback_query(OneTimePaymentSG.payment_method, MenuCb.filter(F.action == "pm"))
async def ot_pm(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    value = callback_data.value
    if value == "new":
        await state.set_state(OneTimePaymentSG.new_payment_method_name)
        await callback.message.edit_text(
            screen(title(Icon.CARD, "Новая карта"), "Название способа оплаты"),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if value == "skip":
        await state.update_data(payment_method_id=None)
    else:
        try:
            payment_method_id = int(value)
        except (TypeError, ValueError):
            await callback.answer(PAYMENT_METHOD_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        method = await PaymentMethodRepository(session).get_active_for_user(
            payment_method_id,
            db_user.id,
        )
        if method is None:
            await callback.answer(PAYMENT_METHOD_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        await state.update_data(payment_method_id=method.id)
    await callback.message.edit_text("Ок")
    await _go_friends(callback.message, state, session, db_user)
    await callback.answer()


@router.message(OneTimePaymentSG.new_payment_method_name, NotNavigationOrCommand())
async def ot_new_pm(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название.")
        return
    method = await PaymentMethodRepository(session).create(user_id=db_user.id, name=name)
    await state.update_data(payment_method_id=method.id)
    await _go_friends(message, state, session, db_user)


@router.callback_query(OneTimePaymentSG.friends, MenuCb.filter(F.action == "ftoggle"))
async def ot_friends_toggle(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    data = await state.get_data()
    selected = set(data.get("selected_friend_ids") or [])
    value = callback_data.value

    if value == "new":
        await state.set_state(OneTimePaymentSG.new_friend_name)
        await callback.message.edit_text(screen(title(Icon.DEBTS, "Новый друг"), "Имя"), parse_mode="HTML")
        await callback.answer()
        return

    if value == "none":
        await state.update_data(selected_friend_ids=[], include_owner=True, split_mode=None)
        await state.set_state(OneTimePaymentSG.confirm)
        text = await _preview(state, session, db_user)
        await callback.message.edit_text(text, reply_markup=confirm_payment_keyboard(), parse_mode="HTML")
        await callback.answer()
        return

    if value == "done":
        requested_friend_ids = set(selected)
        friends = await FriendRepository(session).list_by_ids_for_user(
            requested_friend_ids,
            db_user.id,
        )
        if {friend.id for friend in friends} != requested_friend_ids:
            await state.update_data(selected_friend_ids=[])
            available_friends = await FriendRepository(session).list_for_user(db_user.id)
            await callback.message.edit_reply_markup(
                reply_markup=friends_select_keyboard(available_friends, set()),
            )
            await callback.answer(FRIENDS_UNAVAILABLE_MESSAGE, show_alert=True)
            return
        await state.update_data(selected_friend_ids=list(selected))
        if not selected:
            await state.update_data(include_owner=True, split_mode=None)
            await state.set_state(OneTimePaymentSG.confirm)
            text = await _preview(state, session, db_user)
            await callback.message.edit_text(text, reply_markup=confirm_payment_keyboard(), parse_mode="HTML")
        else:
            await state.set_state(OneTimePaymentSG.include_owner)
            await callback.message.edit_text(
                screen(title(Icon.SPLIT, "Кто участвует"), "Включать тебя в деление?"),
                reply_markup=yes_no_keyboard("own"),
                parse_mode="HTML",
            )
        await callback.answer()
        return

    try:
        friend_id = int(value)
    except (TypeError, ValueError):
        await callback.answer(FRIENDS_UNAVAILABLE_MESSAGE, show_alert=True)
        return
    friend = await FriendRepository(session).get_for_user(friend_id, db_user.id)
    if friend is None:
        await callback.answer(FRIENDS_UNAVAILABLE_MESSAGE, show_alert=True)
        return
    if friend_id in selected:
        selected.remove(friend_id)
    else:
        selected.add(friend_id)
    await state.update_data(selected_friend_ids=list(selected))
    friends = await FriendRepository(session).list_for_user(db_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=friends_select_keyboard(friends, selected),
    )
    await callback.answer()


@router.message(OneTimePaymentSG.new_friend_name, NotNavigationOrCommand())
async def ot_new_friend(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи имя.")
        return
    friend = await FriendRepository(session).create(user_id=db_user.id, name=name)
    data = await state.get_data()
    selected = set(data.get("selected_friend_ids") or [])
    selected.add(friend.id)
    await state.update_data(selected_friend_ids=list(selected))
    await state.set_state(OneTimePaymentSG.friends)
    friends = await FriendRepository(session).list_for_user(db_user.id)
    await message.answer(
        f"Добавлен: {escape_html(name)}",
        reply_markup=friends_select_keyboard(friends, selected),
        parse_mode="HTML",
    )


@router.callback_query(OneTimePaymentSG.include_owner, MenuCb.filter(F.action == "own"))
async def ot_include_owner(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    await state.update_data(include_owner=callback_data.value == "yes")
    await state.set_state(OneTimePaymentSG.split_mode)
    await callback.message.edit_text(
        screen(title(Icon.SPLIT, "Как делить"), "Выбери способ"),
        reply_markup=split_mode_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(OneTimePaymentSG.split_mode, MenuCb.filter(F.action == "sm"))
async def ot_split_mode(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    value = callback_data.value
    if value == "none":
        await state.update_data(split_mode=None)
    else:
        await state.update_data(split_mode=SplitMode.EQUAL.value)
    await state.set_state(OneTimePaymentSG.confirm)
    text = await _preview(state, session, db_user)
    await callback.message.edit_text(text, reply_markup=confirm_payment_keyboard(), parse_mode="HTML")
    await callback.answer()


async def _preview(state: FSMContext, session: AsyncSession, db_user: User) -> str:
    data = await state.get_data()
    amount = Decimal(data["amount"])
    currency = data["currency"]
    pay_date = date.fromisoformat(data["payment_date"])

    rub: Decimal | None = None
    rate: Decimal | None = None

    try:
        conv = await CurrencyConverter(session).convert_to_rub(amount, currency, pay_date)
        rub = conv.rub_amount
        rate = conv.unit_rate_rub
    except Exception:  # noqa: BLE001
        pass

    friend_ids = list(data.get("selected_friend_ids") or [])
    friends = await FriendRepository(session).list_for_user(db_user.id)
    id_to_name = {f.id: f.name for f in friends}
    names = [id_to_name[fid] for fid in friend_ids if fid in id_to_name]
    include_owner = bool(data.get("include_owner", True))
    split_mode = data.get("split_mode")

    people: list[str] = []
    if include_owner and split_mode:
        people.append("Ты")
    people.extend(names)

    blocks: list[str] = [
        entity_name(Icon.HOTEL, data["name"]),
        field(Icon.MONEY, Copy.COST_LABEL, money(amount, currency)),
    ]
    if currency != CurrencyCode.RUB.value:
        if rub is not None:
            blocks.append(field(Icon.RATE, Copy.EQUIV_LABEL, f"≈ {money(rub, CurrencyCode.RUB.value)}"))
        if rate is not None:
            blocks.append(rate_line(Copy.RATE_CBR_LABEL, rate, currency))
        elif rub is None:
            blocks.append(field(Icon.RATE, Copy.RATE_CBR_LABEL, Copy.RATE_UNAVAILABLE))

    if people:
        blocks.append(
            field(
                Icon.DEBTS,
                Copy.SPLIT_BETWEEN_LABEL,
                bullets(*[escape_html(p) for p in people]),
            )
        )
        blocks.append(field(Icon.PEOPLE, "Всего", f"{len(people)} человек"))
        if split_mode == SplitMode.EQUAL.value and rub is not None and people:
            share = quantize_money(rub / len(people))
            blocks.append(field(Icon.MONEY, Copy.PER_PERSON_LABEL, f"≈ {money(share, CurrencyCode.RUB.value)}"))

    blocks.append(field(Icon.CALENDAR, Copy.DATE_LABEL, format_date_ru_short(pay_date)))

    footer = Copy.RUB_HINT_CBR if currency != CurrencyCode.RUB.value and rub is not None else None
    return screen(title(Icon.CHECK, "Проверь платёж"), *blocks, footer=footer)


@router.callback_query(OneTimePaymentSG.confirm, MenuCb.filter(F.action == "pay_confirm"))
async def ot_confirm(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if callback_data.value == "no":
        await state.clear()
        await callback.message.edit_text(screen(title(Icon.CROSS, Copy.CANCELLED)), parse_mode="HTML")
        await callback.message.answer(Copy.OPEN_HOME, reply_markup=main_menu_keyboard())
        await callback.answer()
        return

    data = await state.get_data()
    friend_ids = list(data.get("selected_friend_ids") or [])
    dto = CreateOneTimePaymentDTO(
        user_id=db_user.id,
        name=data["name"],
        category=SubscriptionCategory.OTHER.value,
        original_amount=Decimal(data["amount"]),
        original_currency=data["currency"],
        transaction_date=date.fromisoformat(data["payment_date"]),
        payment_method_id=data.get("payment_method_id"),
        conversion_mode=ConversionMode.CBR.value,
        include_owner_in_split=bool(data.get("include_owner", True)),
        split_mode=data.get("split_mode"),
        friend_ids=friend_ids,
    )
    try:
        tx = await TransactionService(session).create_one_time(dto)
    except FriendsUnavailableError:
        await state.update_data(selected_friend_ids=[])
        await state.set_state(OneTimePaymentSG.friends)
        friends = await FriendRepository(session).list_for_user(db_user.id)
        await callback.message.edit_text(
            FRIENDS_UNAVAILABLE_MESSAGE,
            reply_markup=friends_select_keyboard(friends, set()),
        )
        await callback.answer()
        return
    except PaymentMethodUnavailableError:
        await state.update_data(payment_method_id=None)
        await _go_payment_method(callback.message, state, session, db_user, edit=True)
        await callback.answer(PAYMENT_METHOD_UNAVAILABLE_MESSAGE, show_alert=True)
        return
    except (MoneyError, LookupError, ValueError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    debt_blocks: list[str] = []
    friend_debts = [d for d in (tx.debts or []) if d.friend]
    if friend_debts:
        lines = [f"{escape_html(d.friend.name)}\n{money(Decimal(d.amount_rub), CurrencyCode.RUB.value)}" for d in friend_debts]
        debt_blocks.append(field(Icon.DEBTS, Copy.DEBTS_CREATED_LABEL, "\n\n".join(lines)))
        footer = Copy.DEBTS_ADDED_FOOTER
    else:
        footer = None

    text = success_screen(
        Copy.PAYMENT_SAVED,
        entity_name(Icon.HOTEL, tx.name),
        *debt_blocks,
        footer=footer,
    )
    await callback.message.edit_text(
        text,
        reply_markup=payment_saved_keyboard(transaction_id=tx.id, has_debts=bool(friend_debts)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MenuCb.filter(F.action == "nav"))
async def ot_nav(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await state.clear()
    if callback_data.value == "debts":
        from app.handlers.debts import _render_debts

        await _render_debts(callback.message, session, db_user, edit=True)
        await callback.answer()
        return
    if callback_data.value == "home":
        from app.ui.home import build_home_screen

        text = await build_home_screen(session, db_user)
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.message.answer(Copy.OPEN_HOME, reply_markup=main_menu_keyboard())
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "ot_view"))
async def ot_view_saved(
    callback: CallbackQuery,
    callback_data: TxCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    from app.repositories.transactions import TransactionRepository

    tx = await TransactionRepository(session).get_for_user(callback_data.tid, db_user.id)
    if tx is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    rub = tx.actual_rub_amount or tx.estimated_rub_amount
    blocks = [
        entity_name(Icon.HOTEL, tx.name),
        field(Icon.MONEY, Copy.COST_LABEL, money(Decimal(tx.original_amount), tx.original_currency)),
    ]
    if rub is not None and tx.original_currency != CurrencyCode.RUB.value:
        blocks.append(field(Icon.RATE, Copy.EQUIV_LABEL, f"≈ {money(Decimal(rub), CurrencyCode.RUB.value)}"))
    blocks.append(field(Icon.CALENDAR, Copy.DATE_LABEL, format_date_ru_short(tx.transaction_date)))
    await callback.message.edit_text(
        screen(title(Icon.PAYMENT, "Платёж"), *blocks),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(TxCb.filter(F.action == "ot_edit"))
async def ot_edit_hint(callback: CallbackQuery) -> None:
    await callback.answer("Изменение платежа скоро появится", show_alert=True)
