"""Settings handlers (timezone, methods, friends, wipe)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import NotNavigationOrCommand
from app.keyboards.main_menu import BTN_SETTINGS, main_menu_keyboard
from app.models.debt import Debt
from app.models.friend import Friend
from app.models.payment_method import PaymentMethod
from app.models.reminder_delivery import ReminderDelivery
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.friends import FriendRepository
from app.repositories.payment_methods import PaymentMethodRepository
from app.services.subscription_cards import format_reminder_offsets
from app.ui.presentation import screen
from app.utils.callback_data import MenuCb
from app.utils.telegram import escape_html

router = Router(name="settings")


class SettingsSG(StatesGroup):
    timezone = State()
    reminder_time = State()
    new_friend = State()
    new_method = State()
    wipe_confirm = State()


def settings_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="🕐 Часовой пояс", callback_data=MenuCb(action="set", value="tz").pack())
    b.button(text="⏰ Время уведомлений", callback_data=MenuCb(action="set", value="rtime").pack())
    b.button(text="💳 Способы оплаты", callback_data=MenuCb(action="set", value="pm").pack())
    b.button(text="👥 Друзья", callback_data=MenuCb(action="set", value="friends").pack())
    b.button(text="💱 Валюта · рубли", callback_data=MenuCb(action="set", value="disp").pack())
    b.button(text="📤 Экспорт", callback_data=MenuCb(action="set", value="export").pack())
    b.button(text="🗑 Удалить всё", callback_data=MenuCb(action="set", value="wipe").pack())
    b.adjust(1)
    return b.as_markup()


@router.message(F.text == BTN_SETTINGS)
@router.message(Command("settings"))
async def open_settings(message: Message, state: FSMContext, db_user: User) -> None:
    await state.clear()
    reminders = format_reminder_offsets(list(db_user.default_reminder_offsets or []))
    text = screen(
        "⚙️ <b>Настройки</b>",
        f"🕐 Часовой пояс\n{escape_html(db_user.timezone)}",
        f"⏰ Время уведомлений\n{escape_html(db_user.default_reminder_time)}",
        f"🔔 Напоминания\n{reminders}",
        "💱 Валюта экрана\nРубли",
    )
    await message.answer(text, reply_markup=settings_keyboard(), parse_mode="HTML")


@router.callback_query(MenuCb.filter(F.action == "set"))
async def settings_action(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    value = callback_data.value
    if value == "tz":
        await state.set_state(SettingsSG.timezone)
        await callback.message.edit_text(
            screen(
                "🕐 <b>Часовой пояс</b>",
                "Напиши город в международном виде.\nНапример: Europe/Moscow или Asia/Almaty",
            ),
            parse_mode="HTML",
        )
    elif value == "rtime":
        await state.set_state(SettingsSG.reminder_time)
        await callback.message.edit_text(
            screen(
                "⏰ <b>Время уведомлений</b>",
                "Во сколько присылать напоминания?\nНапример: 10:00",
            ),
            parse_mode="HTML",
        )
    elif value == "disp":
        await callback.answer("Пока показываем только рубли", show_alert=True)
        return
    elif value == "export":
        await callback.answer("Скоро появится", show_alert=True)
        return
    elif value == "pm":
        methods = await PaymentMethodRepository(session).list_active(db_user.id)
        if methods:
            body = "\n".join(f"— {escape_html(m.name)}" for m in methods)
        else:
            body = "Пока пусто"
        await state.set_state(SettingsSG.new_method)
        await callback.message.edit_text(
            screen("💳 <b>Способы оплаты</b>", body, footer="Отправь название, чтобы добавить"),
            parse_mode="HTML",
        )
    elif value == "friends":
        friends = await FriendRepository(session).list_for_user(db_user.id)
        if friends:
            body = "\n".join(f"— {escape_html(f.name)}" for f in friends)
        else:
            body = "Пока пусто"
        await state.set_state(SettingsSG.new_friend)
        await callback.message.edit_text(
            screen("👥 <b>Друзья</b>", body, footer="Отправь имя, чтобы добавить"),
            parse_mode="HTML",
        )
    elif value == "wipe":
        await state.set_state(SettingsSG.wipe_confirm)
        await state.update_data(wipe_step=1)
        await callback.message.edit_text(
            screen(
                "⚠️ <b>Удалить все данные?</b>",
                "Это необратимо.\nПервое подтверждение — напиши:\nУДАЛИТЬ",
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(SettingsSG.timezone, NotNavigationOrCommand())
async def set_tz(message: Message, state: FSMContext, db_user: User) -> None:
    raw = (message.text or "").strip()
    try:
        ZoneInfo(raw)
    except Exception:  # noqa: BLE001
        await message.answer(
            "Не получилось распознать пояс.\nПопробуй: Europe/Moscow"
        )
        return
    db_user.timezone = raw
    await state.clear()
    await message.answer(
        f"✅ Часовой пояс сохранён\n\n{escape_html(raw)}",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(SettingsSG.reminder_time, NotNavigationOrCommand())
async def set_rtime(message: Message, state: FSMContext, db_user: User) -> None:
    raw = (message.text or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("Напиши время как 10:00")
        return
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await message.answer("Такого времени нет. Пример: 09:30")
        return
    db_user.default_reminder_time = f"{h:02d}:{m:02d}"
    await state.clear()
    await message.answer(
        f"✅ Время уведомлений\n\n{db_user.default_reminder_time}",
        reply_markup=main_menu_keyboard(),
    )


@router.message(SettingsSG.new_friend, NotNavigationOrCommand())
async def add_friend(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи имя.")
        return
    await FriendRepository(session).create(user_id=db_user.id, name=name)
    await state.clear()
    await message.answer(
        f"✅ Друг добавлен\n\n{escape_html(name)}",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(SettingsSG.new_method, NotNavigationOrCommand())
async def add_method(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название.")
        return
    await PaymentMethodRepository(session).create(user_id=db_user.id, name=name)
    await state.clear()
    await message.answer(
        f"✅ Способ оплаты добавлен\n\n{escape_html(name)}",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.message(SettingsSG.wipe_confirm, NotNavigationOrCommand())
async def wipe_data(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    data = await state.get_data()
    step = int(data.get("wipe_step", 1))
    text = (message.text or "").strip()
    if step == 1:
        if text != "УДАЛИТЬ":
            await state.clear()
            await message.answer("Удаление отменено.", reply_markup=main_menu_keyboard())
            return
        await state.update_data(wipe_step=2)
        await message.answer(
            screen("⚠️ <b>Ещё раз</b>", "Напиши:\nУДАЛИТЬ ВСЁ"),
            parse_mode="HTML",
        )
        return
    if text != "УДАЛИТЬ ВСЁ":
        await state.clear()
        await message.answer("Удаление отменено.", reply_markup=main_menu_keyboard())
        return

    uid = db_user.id
    await session.execute(delete(ReminderDelivery).where(ReminderDelivery.user_id == uid))
    await session.execute(delete(Debt).where(Debt.user_id == uid))
    await session.execute(delete(Transaction).where(Transaction.user_id == uid))
    await session.execute(delete(Subscription).where(Subscription.user_id == uid))
    await session.execute(delete(PaymentMethod).where(PaymentMethod.user_id == uid))
    await session.execute(delete(Friend).where(Friend.user_id == uid))
    await state.clear()
    await message.answer("✅ Все данные удалены.", reply_markup=main_menu_keyboard())
