"""Render subscription cards via UI Kit components."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.enums import CurrencyCode
from app.models.subscription import Subscription
from app.services.billing_dates import billing_label_short
from app.ui import (
    Copy,
    Icon,
    bullets,
    charge_date_field,
    cost_field,
    entity_card,
    field,
    money,
    money_with_estimate,
    note_field,
    payment_method_field,
    reminders_field,
    repeat_field,
    resolve_subscription_status,
    rub_estimate,
    rub_hint_footer,
    screen,
    status_emoji,
    status_line,
    success_title,
    title,
    txt,
)
from app.utils.dates import format_charge_when


def format_reminder_offsets(offsets: list[int]) -> str:
    if not offsets:
        return "Нет"
    items: list[str] = []
    for off in sorted(offsets, reverse=True):
        if off == 0:
            items.append("В день списания")
        elif off == 1:
            items.append("За день")
        else:
            unit = "дня" if off < 5 else "дней"
            items.append(f"За {off} {unit}")
    return bullets(*items)


def _card_heading(raw: str | None) -> str:
    if not raw:
        return title(Icon.SUBSCRIPTION, "Подписка")
    if raw.startswith("✅"):
        return success_title(raw.removeprefix("✅").strip())
    if "<b>" in raw:
        return raw
    # Already icon-prefixed plain text
    for icon in (Icon.SUBSCRIPTION, Icon.EDIT, Icon.CHECK):
        if raw.startswith(icon):
            rest = raw[len(icon) :].strip()
            return f"{icon} <b>{rest}</b>" if rest else raw
    return title(Icon.SUBSCRIPTION, raw)


def format_subscription_card(
    sub: Subscription,
    *,
    estimated_rub: Decimal | None = None,
    title: str | None = None,
    today: date | None = None,
) -> str:
    status = resolve_subscription_status(sub, today=today)

    rub_amount = estimated_rub
    if rub_amount is None and sub.currency == CurrencyCode.RUB.value:
        rub_amount = Decimal(sub.amount)

    cost_body = money_with_estimate(
        Decimal(sub.amount),
        sub.currency,
        estimated_rub=rub_amount if sub.currency != CurrencyCode.RUB.value else None,
    )

    period = billing_label_short(
        sub.billing_type,
        billing_interval=sub.billing_interval,
    )
    when = (
        format_charge_when(sub.next_charge_date, today=today)
        if sub.next_charge_date
        else "Не задана"
    )
    card_name = txt(sub.payment_method.name) if sub.payment_method else "Не указан"
    reminders = format_reminder_offsets(list(sub.reminder_offsets or []))

    fields = [
        cost_field(cost_body),
        charge_date_field(when),
        repeat_field(period),
        payment_method_field(card_name),
        reminders_field(reminders),
    ]
    if sub.notes:
        fields.append(note_field(txt(sub.notes)))

    footer = None
    if sub.currency != CurrencyCode.RUB.value and rub_amount is not None:
        footer = rub_hint_footer()

    return entity_card(
        heading=_card_heading(title),
        name_icon=Icon.SUBSCRIPTION,
        name=sub.name,
        status=status_line(status),
        fields=fields,
        footer=footer,
    )


def format_actual_charge_prompt(
    *,
    name: str,
    amount: Decimal,
    currency: str,
    estimated_rub: Decimal | None,
) -> str:
    """
    Экран ввода фактического списания в ₽ (только для иновалютных подписок).

    Явно выделяет «В РУБЛЯХ» и показывает исходную сумму + ориентир по курсу ЦБ,
    чтобы пользователь не ввёл долларовую/евро сумму по ошибке.
    """
    original = money(amount, currency)
    rate_body = rub_estimate(estimated_rub, currency=currency) or Copy.RATE_UNAVAILABLE
    example = money(estimated_rub, CurrencyCode.RUB.value) if estimated_rub is not None else "1 560,00 ₽"
    instruction = (
        "Теперь введи сумму,\n"
        "которая РЕАЛЬНО списалась с карты <b>В РУБЛЯХ</b>.\n"
        "\n"
        f"Например:\n{example}"
    )
    return screen(
        title(Icon.MONEY, Copy.ACTUAL_CHARGE_TITLE),
        f"<b>{txt(name)}</b>",
        field(Icon.MONEY, Copy.ORIGINAL_AMOUNT_LABEL, original),
        field(Icon.RATE, Copy.RATE_CBR_LABEL, rate_body),
        instruction,
        footer=Copy.BANK_DIFFERS,
    )


def format_subscription_list_title(count: int) -> str:
    return title(Icon.SUBSCRIPTION, "Подписки", count=count)


def format_subscription_list_row(sub: Subscription, *, today: date | None = None) -> str:
    status = resolve_subscription_status(sub, today=today)
    amount = money(Decimal(sub.amount), sub.currency)
    return f"{status_emoji(status)} {sub.name} · {amount}"
