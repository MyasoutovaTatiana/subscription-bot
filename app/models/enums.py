"""Domain enumerations."""

from enum import StrEnum


class SubscriptionCategory(StrEnum):
    AI_WORK = "ai_work"
    VIDEO_MUSIC = "video_music"
    EDUCATION = "education"
    JOBS = "jobs"
    CLOUD = "cloud"
    TRAVEL = "travel"
    OTHER = "other"


CATEGORY_LABELS: dict[SubscriptionCategory, str] = {
    SubscriptionCategory.AI_WORK: "ИИ и работа",
    SubscriptionCategory.VIDEO_MUSIC: "Видео и музыка",
    SubscriptionCategory.EDUCATION: "Образование",
    SubscriptionCategory.JOBS: "Вакансии",
    SubscriptionCategory.CLOUD: "Облако и сервисы",
    SubscriptionCategory.TRAVEL: "Путешествия",
    SubscriptionCategory.OTHER: "Другое",
}


class CurrencyCode(StrEnum):
    """Supported MVP currencies. Extend this enum to add more codes."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    CNY = "CNY"
    JPY = "JPY"
    VND = "VND"
    THB = "THB"
    TRY = "TRY"
    GEL = "GEL"
    KZT = "KZT"
    AMD = "AMD"
    AED = "AED"


CURRENCY_SYMBOLS: dict[CurrencyCode, str] = {
    CurrencyCode.RUB: "₽",
    CurrencyCode.USD: "$",
    CurrencyCode.EUR: "€",
    CurrencyCode.CNY: "¥",
    CurrencyCode.JPY: "¥",
    CurrencyCode.VND: "₫",
    CurrencyCode.THB: "฿",
    CurrencyCode.TRY: "₺",
    CurrencyCode.GEL: "₾",
    CurrencyCode.KZT: "₸",
    CurrencyCode.AMD: "֏",
    CurrencyCode.AED: "د.إ",
}


class BillingType(StrEnum):
    MONTHLY = "monthly"
    EVERY_N_DAYS = "every_n_days"
    YEARLY = "yearly"
    CUSTOM = "custom"
    NONE = "none"


BILLING_LABELS: dict[BillingType, str] = {
    BillingType.MONTHLY: "каждый месяц",
    BillingType.EVERY_N_DAYS: "каждые N дней",
    BillingType.YEARLY: "каждый год",
    BillingType.CUSTOM: "пользовательский интервал",
    BillingType.NONE: "без автоматического повторения",
}


class TransactionType(StrEnum):
    SUBSCRIPTION = "subscription"
    ONE_TIME = "one_time"


class DebtStatus(StrEnum):
    """Lifecycle of a friend debt.

    ``active`` — ожидает оплаты (legacy + default).
    ``needs_review`` — друг сообщил об оплате, владелец проверяет перевод.
    ``paid`` / ``cancelled`` — закрыт.
    """

    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    PAID = "paid"
    CANCELLED = "cancelled"


# Open debts shown in «Кто мне должен» (not paid/cancelled).
OPEN_DEBT_STATUSES: tuple[DebtStatus, ...] = (
    DebtStatus.ACTIVE,
    DebtStatus.NEEDS_REVIEW,
)

DEBT_STATUS_LABELS: dict[DebtStatus, str] = {
    DebtStatus.ACTIVE: "🟡 Ожидает оплаты",
    DebtStatus.NEEDS_REVIEW: "🟠 Нужно проверить перевод",
    DebtStatus.PAID: "🟢 Оплачено",
    DebtStatus.CANCELLED: "Отменён",
}


class ReminderStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class SplitMode(StrEnum):
    EQUAL = "equal"
    PERCENT = "percent"
    FIXED = "fixed"
    CUSTOM_SHARES = "custom_shares"


class ConversionMode(StrEnum):
    CBR = "cbr"
    MANUAL_RATE = "manual_rate"
    ACTUAL_RUB = "actual_rub"


# Default reminder offsets in days before charge (0 = on charge day).
DEFAULT_REMINDER_OFFSETS: tuple[int, ...] = (3, 1, 0)
