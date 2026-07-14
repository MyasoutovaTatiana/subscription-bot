"""
Telegram Bot UI Kit — public API.

Импортируй компоненты отсюда (или из подмодулей), не собирай разметку вручную.

Быстрый старт::

    from app.ui import (
        Icon, Action, Nav, Copy,
        screen, title, field, entity_name, prompt,
        money, money_with_estimate, rub_estimate,
        success_screen, error_screen, warning_screen,
        resolve_subscription_status, status_line,
        main_reply_keyboard,
    )
"""

from app.ui.buttons import back_button, main_reply_keyboard
from app.ui.card import (
    charge_date_field,
    cost_field,
    debts_total_field,
    entity_card,
    note_field,
    payment_method_field,
    reminders_field,
    repeat_field,
    rub_hint_footer,
)
from app.ui.feedback import (
    error_screen,
    error_title,
    human_error,
    info_title,
    notice_screen,
    success_screen,
    success_title,
    toast_cancelled,
    toast_ok,
    warning_screen,
    warning_title,
)
from app.ui.money import money, money_with_estimate, number, rate_line, rub_estimate
from app.ui.status import (
    STATUS_EMOJI,
    STATUS_LABELS,
    SubscriptionStatus,
    resolve_subscription_status,
    status_emoji,
    status_line,
)
from app.ui.text import bullets, entity_name, field, join_blocks, prompt, screen, title, txt
from app.ui.tokens import Action, Copy, Icon, Nav, StatusDot

__all__ = [
    "Action",
    "Copy",
    "Icon",
    "Nav",
    "StatusDot",
    "SubscriptionStatus",
    "STATUS_LABELS",
    "STATUS_EMOJI",
    "back_button",
    "bullets",
    "charge_date_field",
    "cost_field",
    "debts_total_field",
    "entity_card",
    "entity_name",
    "error_screen",
    "error_title",
    "field",
    "human_error",
    "info_title",
    "join_blocks",
    "main_reply_keyboard",
    "money",
    "money_with_estimate",
    "note_field",
    "notice_screen",
    "number",
    "payment_method_field",
    "prompt",
    "rate_line",
    "reminders_field",
    "repeat_field",
    "resolve_subscription_status",
    "rub_estimate",
    "rub_hint_footer",
    "screen",
    "status_emoji",
    "status_line",
    "success_screen",
    "success_title",
    "title",
    "toast_cancelled",
    "toast_ok",
    "txt",
    "warning_screen",
    "warning_title",
]
