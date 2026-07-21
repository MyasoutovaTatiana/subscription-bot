"""APScheduler job: poll and send due reminders."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.subscription import Subscription
from app.models.user import User
from app.repositories.reminders import ReminderRepository
from app.services.currency import CurrencyConverter
from app.services.reminders import find_due_reminders, reminder_headline
from app.ui.presentation import RUB_HINT, format_rub_estimate, screen
from app.ui.tokens import Action
from app.utils.callback_data import SubCb, SubPeriodCb
from app.utils.dates import format_charge_when
from app.utils.money import format_money
from app.utils.telegram import escape_html

logger = logging.getLogger(__name__)


def reminder_actions_keyboard(subscription_id: int, period_date: date):
    period = period_date.strftime("%Y%m%d")
    b = InlineKeyboardBuilder()
    b.button(
        text=Action.CONFIRM_CHARGE,
        callback_data=SubPeriodCb(
            action="charged",
            sid=subscription_id,
            period=period,
        ).pack(),
    )
    b.button(
        text=Action.PROBLEM,
        callback_data=SubCb(action="not_charged", sid=subscription_id).pack(),
    )
    b.adjust(1)
    return b.as_markup()


async def process_reminders_job(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        result = await session.execute(
            select(Subscription)
            .options(
                selectinload(Subscription.user),
                selectinload(Subscription.payment_method),
            )
            .where(Subscription.is_active.is_(True), Subscription.next_charge_date.is_not(None))
        )
        subs = list(result.scalars().all())

        reminder_repo = ReminderRepository(session)
        # Collect known keys for these subs
        keys: set[str] = set()
        for sub in subs:
            for offset in sub.reminder_offsets or []:
                from app.models.reminder_delivery import ReminderDelivery

                key = ReminderDelivery.build_unique_key(sub.id, sub.next_charge_date, offset)  # type: ignore[arg-type]
                existing = await reminder_repo.get_by_unique_key(key)
                if existing and existing.status in {"sent", "pending", "failed"}:
                    # pending older than now will still be resent via list_due path;
                    # treat sent as already done
                    if existing.status == "sent":
                        keys.add(key)

        due = find_due_reminders(subs, now=now, already_sent_keys=keys)
        converter = CurrencyConverter(session)

        for item in due:
            sub = item.subscription
            user: User = sub.user
            created = await reminder_repo.create_pending(
                user_id=user.id,
                subscription_id=sub.id,
                charge_date=item.charge_date,
                reminder_offset=item.offset,
                scheduled_at=item.scheduled_at,
                unique_key=item.unique_key,
            )
            if created is None:
                continue  # already tracked / race

            card = sub.payment_method.name if sub.payment_method else "Не указан"
            amount = format_money(Decimal(sub.amount), sub.currency)
            try:
                conv = await converter.convert_to_rub(
                    Decimal(sub.amount), sub.currency, item.charge_date
                )
                rub_line = format_rub_estimate(conv.rub_amount, currency=sub.currency)
            except Exception as exc:  # noqa: BLE001
                logger.warning("FX for reminder failed: %s", exc)
                rub_line = "≈ курс пока недоступен"

            cost = amount if not rub_line else f"{amount}\n{rub_line}"
            text = screen(
                f"💳 <b>{reminder_headline(item.offset)}</b>",
                f"<b>{escape_html(sub.name)}</b>",
                f"💰 Стоимость\n{cost}",
                f"💳 Способ оплаты\n{escape_html(card)}",
                f"📅 Дата\n{format_charge_when(item.charge_date)}",
                footer=RUB_HINT if "≈" in rub_line and "недоступен" not in rub_line else None,
            )
            try:
                await bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=text,
                    reply_markup=reminder_actions_keyboard(sub.id, item.charge_date),
                    parse_mode="HTML",
                )
                await reminder_repo.mark_sent(created, datetime.now(timezone.utc))
            except TelegramAPIError as exc:
                logger.exception("Failed to send reminder %s", item.unique_key)
                await reminder_repo.mark_failed(created, str(exc))

        await session.commit()


async def process_debt_review_job(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Remind owners to verify transfers after friend reported payment."""
    from datetime import timedelta

    from app.keyboards.debts import debt_owner_keyboard
    from app.repositories.debts import DebtRepository
    from app.ui import Icon, field, money, screen, title
    from app.utils.telegram import escape_html as esc

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        repo = DebtRepository(session)

        # Explicit «Проверить позже» due items + auto stale (>24h in needs_review)
        due = await repo.list_due_review_reminders(now=now)
        stale = await repo.list_stale_needs_review(older_than=now - timedelta(hours=24))
        seen: set[int] = set()

        async def _send(debt) -> None:
            if debt.id in seen:
                return
            seen.add(debt.id)
            user = debt.user
            if user is None:
                return
            friend = debt.friend.name if debt.friend else "Друг"
            tx_name = debt.transaction.name if debt.transaction else "Платёж"
            text = screen(
                title(Icon.BELL, "Проверь перевод"),
                field(Icon.PEOPLE, "От кого", esc(friend)),
                field(Icon.PAYMENT, "Платёж", esc(tx_name)),
                field(Icon.MONEY, "Сумма", money(Decimal(debt.amount_rub), "RUB")),
                "Друг сообщил об оплате — проверь поступление.",
            )
            try:
                await bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=text,
                    reply_markup=debt_owner_keyboard(debt),
                    parse_mode="HTML",
                )
                # Silence for another day unless user taps «Проверить позже» again
                debt.review_remind_at = now + timedelta(hours=24)
            except TelegramAPIError:
                logger.exception("Failed debt review remind for debt %s", debt.id)

        for debt in due:
            await _send(debt)
        for debt in stale:
            await _send(debt)

        await session.commit()
