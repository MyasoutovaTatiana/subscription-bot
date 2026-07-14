"""Home screen — app dashboard via UI Kit."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.debt import Debt
from app.models.enums import DebtStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.ui import Icon, field, money, screen, title, txt


async def build_home_screen(session: AsyncSession, db_user: User) -> str:
    today = date.today()

    subs_count = await session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.user_id == db_user.id, Subscription.is_active.is_(True))
    )
    today_charges = await session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(
            Subscription.user_id == db_user.id,
            Subscription.is_active.is_(True),
            Subscription.next_charge_date == today,
        )
    )
    debts_total = await session.scalar(
        select(func.coalesce(func.sum(Debt.amount_rub), 0)).where(
            Debt.user_id == db_user.id,
            Debt.status.in_([DebtStatus.ACTIVE.value, DebtStatus.NEEDS_REVIEW.value]),
        )
    )

    n_subs = int(subs_count or 0)
    n_today = int(today_charges or 0)
    debt_sum = Decimal(str(debts_total or 0))

    name = txt(db_user.first_name) if db_user.first_name else ""
    greeting = f"Привет, {name}" if name else "Привет"

    if n_today == 0:
        today_line = "нет списаний"
    elif n_today == 1:
        today_line = "1 списание"
    elif 2 <= n_today <= 4:
        today_line = f"{n_today} списания"
    else:
        today_line = f"{n_today} списаний"

    return screen(
        title(Icon.HOME, greeting),
        field(Icon.SUBSCRIPTION, "Подписки", f"{n_subs} активных"),
        field(Icon.CALENDAR, "Сегодня", today_line),
        field(Icon.DEBTS, "Долги", money(debt_sum, "RUB")),
        footer="Выбери раздел в меню ниже",
    )
