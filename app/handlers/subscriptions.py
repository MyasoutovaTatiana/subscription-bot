"""Subscription handlers: add FSM, list, view, edit, delete."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import NotNavigationOrCommand
from app.keyboards.main_menu import BTN_ADD_SUBSCRIPTION, BTN_MY_SUBSCRIPTIONS, main_menu_keyboard
from app.keyboards.subscriptions import (
    billing_types_keyboard,
    categories_keyboard,
    charge_confirmed_keyboard,
    confirm_delete_keyboard,
    confirm_subscription_keyboard,
    currencies_keyboard,
    edit_fields_keyboard,
    friends_step_keyboard,
    payment_methods_keyboard,
    problem_arose_keyboard,
    reminders_keyboard,
    subscription_card_keyboard,
    subscriptions_list_keyboard,
)
from app.models.enums import (
    CATEGORY_LABELS,
    DEFAULT_REMINDER_OFFSETS,
    BillingType,
    CurrencyCode,
    SubscriptionCategory,
)
from app.models.user import User
from app.repositories.friends import FRIENDS_UNAVAILABLE_MESSAGE, FriendsUnavailableError
from app.repositories.payment_methods import (
    PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
    PaymentMethodRepository,
    PaymentMethodUnavailableError,
)
from app.services.billing_dates import billing_label_short
from app.services.charge_cards import format_charge_confirmed
from app.services.charges import (
    CHARGE_DATA_UNAVAILABLE_MESSAGE,
    ChargeDataUnavailableError,
    ChargeService,
)
from app.services.subscription_cards import (
    format_reminder_offsets,
    format_subscription_card,
    format_subscription_list_title,
)
from app.services.subscriptions import CreateSubscriptionDTO, SubscriptionService
from app.states.subscriptions import AddSubscriptionSG, ConfirmChargeSG, EditSubscriptionSG
from app.ui import (
    Copy,
    Icon,
    field,
    human_error,
    screen,
    success_screen,
    title,
    toast_cancelled,
)
from app.ui.presentation import format_rub_estimate
from app.utils.callback_data import MenuCb, SubCb
from app.utils.dates import format_charge_when, parse_user_date
from app.utils.money import MoneyError, format_money, parse_amount
from app.utils.telegram import escape_html

router = Router(name="subscriptions")


# ── entry points ────────────────────────────────────────────────────────────


@router.message(F.text == BTN_ADD_SUBSCRIPTION)
@router.message(Command("add_subscription"))
async def start_add_subscription(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddSubscriptionSG.name)
    await message.answer(
        "➕ <b>Новая подписка</b>\n\nКак называется?\nНапример: ChatGPT Plus",
        parse_mode="HTML",
    )


@router.message(F.text == BTN_MY_SUBSCRIPTIONS)
@router.message(Command("subscriptions"))
async def list_subscriptions(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await state.clear()
    await _send_subscriptions_list(message, session, db_user)


async def _send_subscriptions_list(
    target: Message,
    session: AsyncSession,
    db_user: User,
    *,
    edit: bool = False,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.subscription import Subscription

    result = await session.execute(
        select(Subscription)
        .options(selectinload(Subscription.payment_method))
        .where(Subscription.user_id == db_user.id)
        .order_by(Subscription.is_active.desc(), Subscription.next_charge_date.nulls_last(), Subscription.name)
    )
    all_subs = list(result.scalars().all())

    if not all_subs:
        text = screen(
            "💳 <b>Подписки</b>",
            "Пока пусто",
            footer="Нажми «➕ Подписка», чтобы добавить первую",
        )
        if edit:
            await target.edit_text(text, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return

    text = screen(
        format_subscription_list_title(len(all_subs)),
        "Выбери подписку",
    )
    kb = subscriptions_list_keyboard(all_subs)
    if edit:
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ── add FSM ─────────────────────────────────────────────────────────────────


@router.message(AddSubscriptionSG.name, NotNavigationOrCommand())
async def add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 1 or len(name) > 255:
        await message.answer("Введи название от 1 до 255 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(AddSubscriptionSG.category)
    await message.answer("Выбери категорию:", reply_markup=categories_keyboard())


@router.callback_query(AddSubscriptionSG.category, MenuCb.filter(F.action == "cat"))
async def add_category(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    await state.update_data(category=callback_data.value)
    await state.set_state(AddSubscriptionSG.amount)
    await callback.message.edit_text(
        f"Категория: {CATEGORY_LABELS[SubscriptionCategory(callback_data.value)]}\n\n"
        "Введи сумму (например 20 или 399,90):"
    )
    await callback.answer()


@router.message(AddSubscriptionSG.amount, NotNavigationOrCommand())
async def add_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = parse_amount(message.text or "")
    except MoneyError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(amount=str(amount))
    await state.set_state(AddSubscriptionSG.currency)
    await message.answer("Выбери валюту:", reply_markup=currencies_keyboard())


@router.callback_query(AddSubscriptionSG.currency, MenuCb.filter(F.action == "cur"))
async def add_currency(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    await state.update_data(currency=callback_data.value)
    await state.set_state(AddSubscriptionSG.billing_type)
    await callback.message.edit_text("Выбери периодичность:", reply_markup=billing_types_keyboard())
    await callback.answer()


@router.callback_query(AddSubscriptionSG.billing_type, MenuCb.filter(F.action == "bill"))
async def add_billing_type(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    btype = BillingType(callback_data.value)
    await state.update_data(billing_type=btype.value)
    if btype in {BillingType.EVERY_N_DAYS, BillingType.CUSTOM}:
        await state.set_state(AddSubscriptionSG.billing_interval)
        await callback.message.edit_text(
            "Через сколько дней повторять?\nНапример: 30"
        )
    else:
        await state.set_state(AddSubscriptionSG.next_charge_date)
        await callback.message.edit_text(
            "Когда следующее списание?\n"
            "Напиши дату как 20.07.2026\n"
            "Или «нет», если даты пока нет."
        )
    await callback.answer()


@router.message(AddSubscriptionSG.billing_interval, NotNavigationOrCommand())
async def add_billing_interval(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Нужно число дней от 1 и больше. Например: 30")
        return
    await state.update_data(billing_interval=int(raw))
    await state.set_state(AddSubscriptionSG.next_charge_date)
    await message.answer("Когда следующее списание?\nНапиши дату как 20.07.2026")


@router.message(AddSubscriptionSG.next_charge_date, NotNavigationOrCommand())
async def add_next_charge_date(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    raw = (message.text or "").strip().lower()
    data = await state.get_data()
    if raw in {"нет", "no", "-", "пропустить"}:
        if data.get("billing_type") != BillingType.NONE.value:
            await message.answer("Для выбранной периодичности нужна дата следующего списания.")
            return
        await state.update_data(next_charge_date=None, billing_day=None)
    else:
        try:
            next_date = parse_user_date(raw)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        if next_date < date.today():
            await message.answer("Дата уже в прошлом. Укажи сегодня или будущую дату.")
            return
        await state.update_data(next_charge_date=next_date.isoformat(), billing_day=next_date.day)

    await state.set_state(AddSubscriptionSG.payment_method)
    methods = await PaymentMethodRepository(session).list_active(db_user.id)
    await message.answer("Выбери способ оплаты:", reply_markup=payment_methods_keyboard(methods))


@router.callback_query(AddSubscriptionSG.payment_method, MenuCb.filter(F.action == "pm"))
async def add_payment_method(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
) -> None:
    value = callback_data.value
    if value == "new":
        await state.set_state(AddSubscriptionSG.new_payment_method_name)
        await callback.message.edit_text(
            "Название способа оплаты:\nНапример: Иностранная USD или Т-Банк основная"
        )
        await callback.answer()
        return
    if value == "skip":
        await state.update_data(payment_method_id=None)
    else:
        await state.update_data(payment_method_id=int(value))

    await state.set_state(AddSubscriptionSG.reminders)
    await callback.message.edit_text("🔔 Напоминания", reply_markup=reminders_keyboard())
    await callback.answer()


@router.message(AddSubscriptionSG.new_payment_method_name, NotNavigationOrCommand())
async def add_new_payment_method(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    name = (message.text or "").strip()
    if len(name) < 1:
        await message.answer("Введи название.")
        return
    method = await PaymentMethodRepository(session).create(user_id=db_user.id, name=name)
    await state.update_data(payment_method_id=method.id)
    await state.set_state(AddSubscriptionSG.reminders)
    await message.answer(
        f"Способ оплаты «{escape_html(name)}» создан.\nВыбери напоминания:",
        reply_markup=reminders_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(AddSubscriptionSG.reminders, MenuCb.filter(F.action == "rem"))
async def add_reminders(callback: CallbackQuery, callback_data: MenuCb, state: FSMContext, db_user: User) -> None:
    value = callback_data.value
    if value == "default":
        offsets = list(db_user.default_reminder_offsets or DEFAULT_REMINDER_OFFSETS)
    elif value == "none":
        offsets = []
    else:
        offsets = [int(x) for x in value.split(",") if x != ""]
    await state.update_data(
        reminder_offsets=offsets,
        reminder_time=db_user.default_reminder_time,
    )
    await state.set_state(AddSubscriptionSG.friends)
    await callback.message.edit_text(
        "👥 Друзья\n\nУчитывать кого-то в этой подписке?",
        reply_markup=friends_step_keyboard(),
    )
    await callback.answer()


@router.callback_query(AddSubscriptionSG.friends, MenuCb.filter(F.action == "fr"))
async def add_friends_step(callback: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.update_data(friend_ids=[])
    await state.set_state(AddSubscriptionSG.confirm)
    text = await _preview_text(state, session, db_user)
    await callback.message.edit_text(text, reply_markup=confirm_subscription_keyboard(), parse_mode="HTML")
    await callback.answer()


async def _preview_text(state: FSMContext, session: AsyncSession, db_user: User) -> str:
    data = await state.get_data()
    amount = Decimal(data["amount"])
    currency = data["currency"]
    next_raw = data.get("next_charge_date")
    next_date = date.fromisoformat(next_raw) if next_raw else None
    pm_id = data.get("payment_method_id")
    card = "Не указан"
    if pm_id:
        method = await PaymentMethodRepository(session).get_for_user(pm_id, db_user.id)
        if method:
            card = method.name

    period = billing_label_short(
        data["billing_type"],
        billing_interval=data.get("billing_interval"),
    )

    estimated = None
    if currency == CurrencyCode.RUB.value:
        estimated = amount
    else:
        try:
            from app.services.currency import CurrencyConverter

            on_date = next_date or date.today()
            conv = await CurrencyConverter(session).convert_to_rub(amount, currency, on_date)
            estimated = conv.rub_amount
        except Exception:  # noqa: BLE001
            estimated = None

    cost = format_money(amount, currency)
    rub_line = format_rub_estimate(estimated, currency=currency)
    cost_block = cost if not rub_line else f"{cost}\n{rub_line}"
    when = format_charge_when(next_date) if next_date else "Не задана"
    reminders = format_reminder_offsets(list(data.get("reminder_offsets") or []))

    return screen(
        "✅ Проверь подписку",
        f"💳 <b>{escape_html(data['name'])}</b>",
        f"💰 Стоимость\n{cost_block}",
        f"📅 Следующее списание\n{when}",
        f"🔄 Повтор\n{period}",
        f"💳 Способ оплаты\n{escape_html(card)}",
        f"🔔 Напоминания\n{reminders}",
    )


@router.callback_query(AddSubscriptionSG.confirm, MenuCb.filter(F.action == "sub_confirm"))
async def confirm_create(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if callback_data.value == "no":
        await state.clear()
        await callback.message.edit_text("❌ Создание отменено")
        await callback.message.answer(
            "Открой 🏠 Главная в меню",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()
        return

    data = await state.get_data()
    next_raw = data.get("next_charge_date")
    dto = CreateSubscriptionDTO(
        user_id=db_user.id,
        name=data["name"],
        category=data["category"],
        amount=Decimal(data["amount"]),
        currency=data["currency"],
        billing_type=data["billing_type"],
        billing_interval=data.get("billing_interval"),
        billing_day=data.get("billing_day"),
        next_charge_date=date.fromisoformat(next_raw) if next_raw else None,
        payment_method_id=data.get("payment_method_id"),
        reminder_offsets=list(data.get("reminder_offsets") or []),
        reminder_time=data.get("reminder_time") or db_user.default_reminder_time,
        friend_ids=list(data.get("friend_ids") or []),
    )
    service = SubscriptionService(session)
    try:
        sub = await service.create(dto)
    except FriendsUnavailableError:
        await state.update_data(friend_ids=[])
        await state.set_state(AddSubscriptionSG.friends)
        await callback.message.edit_text(
            FRIENDS_UNAVAILABLE_MESSAGE,
            reply_markup=friends_step_keyboard(),
        )
        await callback.answer()
        return
    except PaymentMethodUnavailableError:
        await state.update_data(payment_method_id=None)
        await state.set_state(AddSubscriptionSG.payment_method)
        methods = await PaymentMethodRepository(session).list_active(db_user.id)
        await callback.message.edit_text(
            PAYMENT_METHOD_UNAVAILABLE_MESSAGE,
            reply_markup=payment_methods_keyboard(methods),
        )
        await callback.answer()
        return
    await state.clear()

    estimated = None
    try:
        from app.services.currency import CurrencyConverter

        on_date = sub.next_charge_date or date.today()
        conv = await CurrencyConverter(session).convert_to_rub(
            Decimal(sub.amount), sub.currency, on_date
        )
        estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None

    card = format_subscription_card(
        sub,
        estimated_rub=estimated,
        title="✅ Подписка создана",
    )
    await callback.message.edit_text(
        card,
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer()


# ── list / view / edit / delete ──────────────────────────────────────────────


@router.callback_query(SubCb.filter(F.action == "list"))
async def cb_list(callback: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await _send_subscriptions_list(callback.message, session, db_user, edit=True)
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "view"))
async def cb_view(
    callback: CallbackQuery,
    callback_data: SubCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    estimated = None
    try:
        from app.services.currency import CurrencyConverter

        on_date = sub.next_charge_date or date.today()
        conv = await CurrencyConverter(session).convert_to_rub(
            Decimal(sub.amount), sub.currency, on_date
        )
        estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None
    await callback.message.edit_text(
        format_subscription_card(sub, estimated_rub=estimated),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "off"))
async def cb_off(callback: CallbackQuery, callback_data: SubCb, session: AsyncSession, db_user: User) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await service.deactivate(sub)
    await callback.message.edit_text(
        format_subscription_card(sub),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer("Приостановлена")


@router.callback_query(SubCb.filter(F.action == "on"))
async def cb_on(callback: CallbackQuery, callback_data: SubCb, session: AsyncSession, db_user: User) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await service.activate(sub)
    await callback.message.edit_text(
        format_subscription_card(sub),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer("Возобновлена")


@router.callback_query(SubCb.filter(F.action == "del"))
async def cb_delete_ask(callback: CallbackQuery, callback_data: SubCb) -> None:
    await callback.message.edit_text(
        "🗑 <b>Удалить подписку?</b>\n\nЭто нельзя отменить.",
        reply_markup=confirm_delete_keyboard(callback_data.sid),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "del_yes"))
async def cb_delete_yes(
    callback: CallbackQuery,
    callback_data: SubCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Уже удалена", show_alert=True)
        return
    await service.delete(sub)
    await callback.answer("Удалено")
    await _send_subscriptions_list(callback.message, session, db_user, edit=True)


@router.callback_query(SubCb.filter(F.action.startswith("ef_")))
async def cb_edit_field(
    callback: CallbackQuery,
    callback_data: SubCb,
    state: FSMContext,
) -> None:
    field = callback_data.action.removeprefix("ef_")
    await state.set_state(EditSubscriptionSG.value)
    await state.update_data(edit_sid=callback_data.sid, edit_field=field)
    prompts = {
        "name": "Новое название",
        "amount": "Новая сумма\nНапример: 20 или 399,90",
        "currency": "Валюта\nНапример: доллары — USD, евро — EUR, рубли — RUB",
        "next_charge_date": "Новая дата\nНапример: 20.07.2026\nИли «нет»",
        "notes": "Заметка\nИли «-», чтобы очистить",
    }
    await callback.message.edit_text(prompts.get(field, "Новое значение:"))
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "edit"))
async def cb_edit_menu(callback: CallbackQuery, callback_data: SubCb) -> None:
    await callback.message.edit_text(
        "✏️ <b>Что изменить?</b>",
        reply_markup=edit_fields_keyboard(callback_data.sid),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "charged"))
async def cb_charged(
    callback: CallbackQuery,
    callback_data: SubCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    try:
        await _complete_charge(
            callback.message,
            session,
            state,
            sub,
            user_id=db_user.id,
            actual_rub=None,
            edit=True,
        )
    except ChargeDataUnavailableError:
        await callback.answer(CHARGE_DATA_UNAVAILABLE_MESSAGE, show_alert=True)
        return
    except Exception as exc:  # noqa: BLE001
        await callback.answer(human_error(str(exc)), show_alert=True)
        return
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "chg_skip"), ConfirmChargeSG.actual_rub)
async def cb_charge_skip(
    callback: CallbackQuery,
    callback_data: SubCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """Legacy skip path — same as confirm without fact."""
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await state.clear()
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    try:
        await _complete_charge(
            callback.message,
            session,
            state,
            sub,
            user_id=db_user.id,
            actual_rub=None,
            edit=True,
        )
    except ChargeDataUnavailableError:
        await callback.answer(CHARGE_DATA_UNAVAILABLE_MESSAGE, show_alert=True)
        return
    except Exception as exc:  # noqa: BLE001
        await callback.answer(human_error(str(exc)), show_alert=True)
        return
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "chg_cancel"), ConfirmChargeSG.actual_rub)
async def cb_charge_cancel(
    callback: CallbackQuery,
    callback_data: SubCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await state.clear()
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.message.edit_text(toast_cancelled())
        await callback.answer()
        return

    estimated = None
    try:
        from app.services.currency import CurrencyConverter

        if sub.next_charge_date:
            conv = await CurrencyConverter(session).convert_to_rub(
                Decimal(sub.amount), sub.currency, sub.next_charge_date
            )
            estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None

    await callback.message.edit_text(
        format_subscription_card(sub, estimated_rub=estimated),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer(toast_cancelled())


@router.message(ConfirmChargeSG.actual_rub, NotNavigationOrCommand())
async def charge_actual_rub_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """Legacy text entry for actual RUB — treat as confirm with given amount."""
    data = await state.get_data()
    sid = int(data.get("charge_sid") or 0)
    service = SubscriptionService(session)
    sub = await service.get(sid, db_user.id)
    if sub is None:
        await state.clear()
        await message.answer("Подписка не найдена.", reply_markup=main_menu_keyboard())
        return

    raw = (message.text or "").strip()
    try:
        amount = parse_amount(raw)
    except MoneyError as exc:
        await message.answer(str(exc))
        return

    try:
        await _complete_charge(
            message,
            session,
            state,
            sub,
            user_id=db_user.id,
            actual_rub=amount,
            edit=False,
        )
    except ChargeDataUnavailableError:
        await message.answer(
            CHARGE_DATA_UNAVAILABLE_MESSAGE,
            reply_markup=main_menu_keyboard(),
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(human_error(str(exc)), reply_markup=main_menu_keyboard())


async def _complete_charge(
    target: Message,
    session: AsyncSession,
    state: FSMContext,
    sub,
    *,
    user_id: int,
    actual_rub: Decimal | None,
    edit: bool,
) -> None:
    _tx, next_date, _estimated, _actual = await ChargeService(session).confirm_charged(
        sub,
        user_id=user_id,
        actual_rub_amount=actual_rub,
    )
    await state.clear()

    text = format_charge_confirmed(next_charge_date=next_date)
    markup = charge_confirmed_keyboard(sub.id)
    if edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(SubCb.filter(F.action == "not_charged"))
async def cb_not_charged(
    callback: CallbackQuery,
    callback_data: SubCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    text = screen(
        title(Icon.PROBLEM, Copy.PROBLEM_TITLE),
        field(Icon.SUBSCRIPTION, "Подписка", escape_html(sub.name)),
    )
    await callback.message.edit_text(
        text,
        reply_markup=problem_arose_keyboard(sub.id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "prob_nomoney"))
@router.callback_query(SubCb.filter(F.action == "prob_date"))
async def cb_prob_new_date(
    callback: CallbackQuery,
    callback_data: SubCb,
    state: FSMContext,
) -> None:
    await state.set_state(EditSubscriptionSG.value)
    await state.update_data(edit_sid=callback_data.sid, edit_field="next_charge_date")
    reason = "Не хватило денег" if callback_data.action == "prob_nomoney" else "Дата изменилась"
    await callback.message.edit_text(
        screen(
            title(Icon.CALENDAR, Copy.PICK_DATE_TITLE),
            reason,
            "Например: 20.07.2026",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "prob_price"))
async def cb_prob_price(callback: CallbackQuery, callback_data: SubCb, state: FSMContext) -> None:
    await state.set_state(EditSubscriptionSG.value)
    await state.update_data(edit_sid=callback_data.sid, edit_field="amount")
    await callback.message.edit_text(
        screen(title(Icon.MONEY, "Новая стоимость"), "Введи сумму подписки"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "prob_cancel"))
async def cb_prob_cancel(
    callback: CallbackQuery,
    callback_data: SubCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    service = SubscriptionService(session)
    sub = await service.get(callback_data.sid, db_user.id)
    if sub is None:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    await service.deactivate(sub)
    await callback.message.edit_text(
        success_screen("Подписка приостановлена", escape_html(sub.name)),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "prob_del"))
async def cb_prob_del(callback: CallbackQuery, callback_data: SubCb) -> None:
    await callback.message.edit_text(
        screen(title(Icon.TRASH, "Удалить подписку?"), "Это действие нельзя отменить."),
        reply_markup=confirm_delete_keyboard(callback_data.sid),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "chg_amt"))
async def cb_chg_amt(callback: CallbackQuery, callback_data: SubCb, state: FSMContext) -> None:
    await state.set_state(EditSubscriptionSG.value)
    await state.update_data(edit_sid=callback_data.sid, edit_field="amount")
    await callback.message.answer("Новая сумма подписки:")
    await callback.answer()


@router.callback_query(SubCb.filter(F.action == "chg_date"))
async def cb_chg_date(callback: CallbackQuery, callback_data: SubCb, state: FSMContext) -> None:
    await state.set_state(EditSubscriptionSG.value)
    await state.update_data(edit_sid=callback_data.sid, edit_field="next_charge_date")
    await callback.message.answer("Новая дата списания\nНапример: 20.07.2026")
    await callback.answer()


@router.message(EditSubscriptionSG.value, NotNavigationOrCommand())
async def apply_edit(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    sid = int(data["edit_sid"])
    field = data["edit_field"]
    raw = (message.text or "").strip()
    service = SubscriptionService(session)
    sub = await service.get(sid, db_user.id)
    if sub is None:
        await state.clear()
        await message.answer("Подписка не найдена.", reply_markup=main_menu_keyboard())
        return

    try:
        if field == "actual_rub_after_charge":
            # Совместимость со старыми FSM-сессиями (до ask-first UX).
            from app.repositories.transactions import TransactionRepository

            amount = parse_amount(raw)
            tx_id = int(data.get("tx_id") or 0)
            tx = await TransactionRepository(session).get_for_user(tx_id, db_user.id)
            if tx is None:
                raise ValueError("Платёж не найден")
            await TransactionRepository(session).update_actual_rub(tx, amount)
            await state.clear()
            estimated = None
            try:
                from app.services.currency import CurrencyConverter

                if sub.next_charge_date:
                    conv = await CurrencyConverter(session).convert_to_rub(
                        Decimal(sub.amount), sub.currency, sub.next_charge_date
                    )
                    estimated = conv.rub_amount
            except Exception:  # noqa: BLE001
                estimated = None
            await message.answer(
                format_subscription_card(
                    sub,
                    estimated_rub=estimated,
                    title=Copy.CHARGE_SAVED,
                ),
                reply_markup=subscription_card_keyboard(sub),
                parse_mode="HTML",
            )
            return
        if field == "name":
            if not raw:
                raise ValueError("Название не может быть пустым")
            sub.name = raw
        elif field == "amount":
            sub.amount = parse_amount(raw)
        elif field == "currency":
            code = raw.upper()
            CurrencyCode(code)  # validate
            sub.currency = code
        elif field == "next_charge_date":
            if raw.lower() in {"нет", "no", "-"}:
                sub.next_charge_date = None
            else:
                sub.next_charge_date = parse_user_date(raw)
                sub.billing_day = sub.next_charge_date.day
        elif field == "notes":
            sub.notes = None if raw in {"-", ""} else raw
    except (MoneyError, ValueError) as exc:
        await message.answer(str(exc))
        return

    await service.update_fields(sub)
    await state.clear()

    estimated = None
    try:
        from app.services.currency import CurrencyConverter

        if sub.next_charge_date:
            conv = await CurrencyConverter(session).convert_to_rub(
                Decimal(sub.amount), sub.currency, sub.next_charge_date
            )
            estimated = conv.rub_amount
    except Exception:  # noqa: BLE001
        estimated = None

    await message.answer(
        format_subscription_card(sub, estimated_rub=estimated, title="✅ Обновлено"),
        reply_markup=subscription_card_keyboard(sub),
        parse_mode="HTML",
    )
