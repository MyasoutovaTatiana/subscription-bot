"""Debts handlers — owner list + two-stage payment confirmation."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters import NotNavigationOrCommand
from app.keyboards.debts import (
    debt_owner_keyboard,
    debt_status_label,
    debts_list_keyboard,
    friend_debt_keyboard,
)
from app.keyboards.main_menu import BTN_DEBTS, main_menu_keyboard
from app.models.enums import DebtStatus
from app.models.user import User
from app.repositories.debts import DebtRepository
from app.ui import Copy, Icon, entity_name, field, money, screen, success_screen, title, warning_screen
from app.utils.callback_data import DebtCb
from app.utils.money import MoneyError, parse_amount
from app.utils.telegram import escape_html

router = Router(name="debts")


class EditDebtSG(StatesGroup):
    amount = State()


def _owner_first_name(user: User | None) -> str:
    if user and user.first_name:
        return user.first_name
    return "Владелец"


async def _render_debts(
    target: Message,
    session: AsyncSession,
    db_user: User,
    *,
    edit: bool = False,
) -> None:
    repo = DebtRepository(session)
    debts = await repo.list_open(db_user.id)
    total = await repo.total_open_rub(db_user.id)

    if not debts:
        text = screen(title(Icon.DEBTS, "Кто мне должен"), "Пока никто не должен")
        if edit:
            await target.edit_text(text, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return

    by_friend: dict[str, list] = defaultdict(list)
    sums: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for debt in debts:
        name = debt.friend.name if debt.friend else "Друг"
        by_friend[name].append(debt)
        sums[name] += Decimal(debt.amount_rub)

    blocks: list[str] = [field(Icon.MONEY, "Всего", money(total, "RUB"))]
    for name, items in sorted(by_friend.items(), key=lambda x: x[0].lower()):
        lines = [f"<b>{escape_html(name)}</b> · {money(sums[name], 'RUB')}"]
        for debt in items:
            tx_name = debt.transaction.name if debt.transaction else "Платёж"
            lines.append(f"{debt_status_label(debt.status)}")
            lines.append(f"— {escape_html(tx_name)}")
        blocks.append("\n".join(lines))

    text = screen(title(Icon.DEBTS, "Кто мне должен"), *blocks)
    kb = debts_list_keyboard(debts)
    if edit:
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(F.text == BTN_DEBTS)
@router.message(Command("debts"))
async def show_debts(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    await _render_debts(message, session, db_user)


def _owner_debt_card(debt) -> str:
    friend = debt.friend.name if debt.friend else "Друг"
    tx_name = debt.transaction.name if debt.transaction else "Платёж"
    return screen(
        title(Icon.DEBTS, "Долг"),
        entity_name(Icon.PEOPLE, friend),
        field(Icon.PAYMENT, "Платёж", escape_html(tx_name)),
        field(Icon.MONEY, "Сумма", money(Decimal(debt.amount_rub), "RUB")),
        field(Icon.INFO, "Статус", debt_status_label(debt.status)),
    )


@router.callback_query(DebtCb.filter(F.action == "list"))
async def cb_list(callback: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await _render_debts(callback.message, session, db_user, edit=True)
    await callback.answer()


@router.callback_query(DebtCb.filter(F.action == "view"))
async def cb_view(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    debt = await DebtRepository(session).get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.edit_text(
        _owner_debt_card(debt),
        reply_markup=debt_owner_keyboard(debt),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(DebtCb.filter(F.action == "share"))
async def cb_share(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
    bot: Bot,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    token = await repo.ensure_share_token(debt)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=debt_{token}"
    friend = debt.friend.name if debt.friend else "другу"
    await callback.message.edit_text(
        screen(
            title(Icon.DEBTS, "Ссылка для друга"),
            entity_name(Icon.PEOPLE, friend),
            field(Icon.MONEY, "Сумма", money(Decimal(debt.amount_rub), "RUB")),
            Copy.SHARE_LINK_HINT,
            f"<code>{escape_html(link)}</code>",
        ),
        reply_markup=debt_owner_keyboard(debt),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(DebtCb.filter(F.action == "money_ok"))
async def cb_money_ok(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
    bot: Bot,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.mark_paid(debt)
    owner_name = _owner_first_name(db_user)
    if debt.payer_telegram_id:
        try:
            await bot.send_message(
                chat_id=debt.payer_telegram_id,
                text=success_screen(
                    f"{escape_html(owner_name)} подтвердила получение денег.",
                    "Спасибо!",
                ),
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass
    await callback.answer("Оплата подтверждена")
    await _render_debts(callback.message, session, db_user, edit=True)


@router.callback_query(DebtCb.filter(F.action == "money_no"))
async def cb_money_no(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
    bot: Bot,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.reopen_awaiting(debt)
    owner_name = _owner_first_name(db_user)
    if debt.payer_telegram_id:
        try:
            await bot.send_message(
                chat_id=debt.payer_telegram_id,
                text=warning_screen(
                    f"{escape_html(owner_name)} пока не видит перевод.",
                    "Возможно,\nбанк ещё проводит операцию.",
                ),
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass
    await callback.message.edit_text(
        _owner_debt_card(debt),
        reply_markup=debt_owner_keyboard(debt),
        parse_mode="HTML",
    )
    await callback.answer("Вернули в ожидание")


@router.callback_query(DebtCb.filter(F.action == "check_later"))
async def cb_check_later(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    if debt.status != DebtStatus.NEEDS_REVIEW.value:
        await callback.answer("Сначала дождись сообщения друга", show_alert=True)
        return
    await repo.schedule_review_reminder(debt, hours=24)
    await callback.message.edit_text(
        success_screen(Copy.REMIND_LATER_SET),
        reply_markup=debt_owner_keyboard(debt),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(DebtCb.filter(F.action == "cancel"))
async def cb_cancel(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.cancel(debt)
    await callback.answer("Отменён")
    await _render_debts(callback.message, session, db_user, edit=True)


@router.callback_query(DebtCb.filter(F.action == "edit"))
async def cb_edit(
    callback: CallbackQuery,
    callback_data: DebtCb,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    debt = await DebtRepository(session).get_for_user(callback_data.did, db_user.id)
    if debt is None:
        await callback.answer("Долг не найден", show_alert=True)
        return
    await state.set_state(EditDebtSG.amount)
    await state.update_data(debt_id=callback_data.did)
    await callback.message.edit_text(screen(title(Icon.EDIT, "Новая сумма"), "Введи сумму в ₽"), parse_mode="HTML")
    await callback.answer()


@router.message(EditDebtSG.amount, NotNavigationOrCommand())
async def edit_debt_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    try:
        amount = parse_amount(message.text or "")
    except MoneyError as exc:
        await message.answer(str(exc))
        return
    data = await state.get_data()
    repo = DebtRepository(session)
    debt = await repo.get_for_user(int(data["debt_id"]), db_user.id)
    await state.clear()
    if debt is None:
        await message.answer("Долг не найден.", reply_markup=main_menu_keyboard())
        return
    await repo.update_amount(debt, amount)
    await message.answer(
        success_screen(Copy.AMOUNT_UPDATED, money(amount, "RUB")),
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


# ── Friend side ──────────────────────────────────────────────────────────────


async def show_friend_debt(
    message: Message,
    session: AsyncSession,
    *,
    token: str,
    telegram_user_id: int,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_by_share_token(token)
    if debt is None:
        await message.answer(
            screen(title(Icon.WARN, "Ссылка недействительна"), "Попроси новую ссылку у друга."),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    if debt.status == DebtStatus.PAID.value:
        await message.answer(
            success_screen("Этот долг уже закрыт", "Спасибо!"),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    if debt.status == DebtStatus.CANCELLED.value:
        await message.answer(
            screen(title(Icon.INFO, "Долг отменён")),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    claimed = await repo.claim_share_token(token, telegram_user_id)
    debt = await repo.get_by_share_token(token)
    if debt is None:
        await message.answer(
            screen(title(Icon.WARN, "Ссылка недействительна"), "Попроси новую ссылку у друга."),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not claimed:
        # Another request may have claimed or closed the debt after our read.
        if debt.status == DebtStatus.PAID.value:
            await message.answer(
                success_screen("Этот долг уже закрыт", "Спасибо!"),
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            return
        if debt.status == DebtStatus.CANCELLED.value:
            await message.answer(
                screen(title(Icon.INFO, "Долг отменён")),
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            return
        await message.answer(
            warning_screen("Эта ссылка уже открыта другим человеком."),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    tx_name = debt.transaction.name if debt.transaction else "Платёж"
    if debt.status == DebtStatus.NEEDS_REVIEW.value:
        owner = _owner_first_name(debt.user)
        await message.answer(
            screen(
                entity_name(Icon.PAYMENT, tx_name),
                field(Icon.MONEY, Copy.YOUR_SHARE, money(Decimal(debt.amount_rub), "RUB")),
                f"✅ {escape_html(owner)} получила уведомление.",
                Copy.DEBT_CLOSES_AFTER,
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        screen(
            entity_name(Icon.PAYMENT, tx_name),
            field(Icon.MONEY, Copy.YOUR_SHARE, money(Decimal(debt.amount_rub), "RUB")),
        ),
        reply_markup=friend_debt_keyboard(debt.id),
        parse_mode="HTML",
    )


@router.callback_query(DebtCb.filter(F.action == "friend_paid"))
async def cb_friend_paid(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
    bot: Bot,
) -> None:
    repo = DebtRepository(session)
    debt = await repo.get_by_id(callback_data.did)
    if debt is None:
        await callback.answer("Не найдено", show_alert=True)
        return

    # Access only for the already-bound payer (binding happens via share-token link).
    if debt.payer_telegram_id is None or debt.payer_telegram_id != db_user.telegram_user_id:
        await callback.answer("Нет доступа", show_alert=True)
        return

    if debt.status == DebtStatus.PAID.value:
        await callback.answer("Долг уже закрыт", show_alert=True)
        return

    if debt.status == DebtStatus.CANCELLED.value:
        await callback.answer("Долг отменён", show_alert=True)
        return

    if debt.status == DebtStatus.NEEDS_REVIEW.value:
        await callback.answer("Информация уже отправлена", show_alert=True)
        return

    if debt.status != DebtStatus.ACTIVE.value:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await repo.mark_payment_reported(debt)
    owner = debt.user
    owner_name = _owner_first_name(owner)
    friend_name = debt.friend.name if debt.friend else db_user.first_name or "Друг"
    tx_name = debt.transaction.name if debt.transaction else "Платёж"

    if owner:
        try:
            await bot.send_message(
                chat_id=owner.telegram_chat_id,
                text=screen(
                    title(Icon.PAYMENT, f"{escape_html(friend_name)} сообщил об оплате"),
                    field(Icon.HOTEL, "Платёж", escape_html(tx_name)),
                    field(Icon.MONEY, "Сумма", money(Decimal(debt.amount_rub), "RUB")),
                    Copy.CHECK_TRANSFER,
                ),
                reply_markup=debt_owner_keyboard(debt),
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass

    await callback.message.edit_text(
        screen(
            title(Icon.CHECK, f"{escape_html(owner_name)} получила уведомление."),
            Copy.DEBT_CLOSES_AFTER,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(DebtCb.filter(F.action == "friend_later"))
async def cb_friend_later(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        screen(title(Icon.CLOCK, "Хорошо"), "Напомни себе перевести, когда будет удобно."),
        parse_mode="HTML",
    )
    await callback.answer()


# Legacy alias kept for old buttons
@router.callback_query(DebtCb.filter(F.action == "paid"))
async def cb_paid_legacy(
    callback: CallbackQuery,
    callback_data: DebtCb,
    session: AsyncSession,
    db_user: User,
    bot: Bot,
) -> None:
    callback_data.action = "money_ok"
    await cb_money_ok(callback, callback_data, session, db_user, bot)
