"""
Telegram Bot UI Kit — design tokens.

Единый визуальный язык потребительского приложения.
Не добавляй эмодзи и формулировки ad-hoc в handlers — бери отсюда.
"""

from __future__ import annotations

# ── Layout ───────────────────────────────────────────────────────────────────

BLANK_LINE = ""  # между блоками карточки/экрана всегда одна пустая строка
LIST_BULLET = "·"  # в заголовках-счётчиках: «Подписки · 12»
FIELD_BULLET = "•"  # в списках внутри поля


# ── Iconography (одна иконка = одно значение) ────────────────────────────────

class Icon:
    HOME = "🏠"
    SUBSCRIPTION = "💳"
    PAYMENT = "💸"
    CALENDAR = "📅"
    DEBTS = "👥"
    SETTINGS = "⚙️"
    MONEY = "💰"
    REPEAT = "🔄"
    BELL = "🔔"
    NOTE = "📝"
    CARD = "💳"
    RATE = "💱"
    SPLIT = "➗"
    HOTEL = "🏨"
    CLOCK = "⏰"
    TZ = "🕐"
    EXPORT = "📤"
    TRASH = "🗑"
    EDIT = "✏️"
    PAUSE = "⏸"
    PLAY = "▶️"
    BACK = "◀️"
    CHECK = "✅"
    CROSS = "❌"
    WARN = "⚠️"
    INFO = "ℹ️"
    SKIP = "⏭"
    OPEN = "💳"
    UNDO = "↩️"
    PROBLEM = "⚙️"
    NO_MONEY = "💳"
    PRICE_CHANGE = "💰"
    CANCEL_SUB = "🚫"
    PEOPLE = "👥"
    PARTY = "🎉"


# ── Semantic status dots ─────────────────────────────────────────────────────

class StatusDot:
    OK = "🟢"
    WARN = "🟡"
    DANGER = "🔴"
    MUTED = "⏸"


# ── Shared microcopy ─────────────────────────────────────────────────────────

class Copy:
    # Soft hint for subscription cards / reminders (без акцента на «ЦБ»).
    RUB_HINT = "Сумма в рублях ориентировочная — банк может списать иначе."
    # Explicit CBR line for one-time payment confirm (product review).
    RUB_HINT_CBR = "ℹ️ Рассчитано по курсу ЦБ.\nФактическое списание может отличаться."
    BANK_DIFFERS = "Фактическое списание может отличаться."
    EMPTY = "Пока пусто"
    NOT_SET = "Не указан"
    DATE_NOT_SET = "Не задана"
    RATE_PENDING = "≈ будет рассчитано автоматически"
    RATE_UNAVAILABLE = "≈ курс пока недоступен"
    RATE_CBR_LABEL = "Курс ЦБ"
    ORIGINAL_AMOUNT_LABEL = "Исходная сумма"
    CANCELLED = "Отменено"
    SAVED = "Сохранено"
    DELETED = "Удалено"
    NOTHING_TO_CANCEL = "Нечего отменять"
    OPEN_HOME = "Открой 🏠 Главная"
    CHARGE_CONFIRMED = "Списание подтверждено"
    CHARGE_ALREADY_CONFIRMED = "Списание уже подтверждено"
    CHARGE_SAVED = "Списание сохранено"
    CHARGE_TITLE = "Списание"
    PROBLEM_TITLE = "Что произошло?"
    AMOUNT_UPDATED = "Сумма обновлена"
    DEBTS_RECALCULATED = "Долги друзей автоматически пересчитаны."
    RATE_UPDATED = "Курс обновлён"
    DATE_UPDATED = "Дата обновлена"
    CHARGE_UNDONE = "Списание отменено"
    CHARGE_DELETED = "Списание удалено"
    AWAITING_CHARGE = "Ожидает списания"
    ESTIMATED_RUB_LABEL = "Ориентировочная сумма"
    ACTUAL_RUB_LABEL = "Фактическая сумма"
    CHARGE_DATE_LABEL = "Дата списания"
    NEXT_CHARGE_LABEL = "Следующее списание"
    COST_LABEL = "Стоимость"
    EQUIV_LABEL = "Эквивалент"
    SPLIT_BETWEEN_LABEL = "Делим между"
    PER_PERSON_LABEL = "На человека"
    DATE_LABEL = "Дата"
    PAYMENT_SAVED = "Платёж сохранён"
    DEBTS_CREATED_LABEL = "Созданы долги"
    DEBTS_ADDED_FOOTER = "Все долги добавлены\nв раздел\n👥 Кто мне должен"
    PICK_DATE_TITLE = "Новая дата списания"
    TODAY = "Сегодня"
    YESTERDAY = "Вчера"
    PICK_DATE = "Выбрать дату"
    YOUR_SHARE = "Твоя часть"
    OWNER_NOTIFIED = "получила уведомление"
    DEBT_CLOSES_AFTER = "Долг закроется\nпосле подтверждения получения денег."
    SHARE_LINK_HINT = "Отправь ссылку другу —\nон отметит, когда переведёт деньги."
    CHECK_TRANSFER = "Проверь поступление денег."
    REMIND_LATER_SET = "Напомню проверить через сутки."


# ── Reply keyboard labels (shell navigation) ─────────────────────────────────

class Nav:
    HOME = f"{Icon.HOME} Главная"
    SUBSCRIPTIONS = f"{Icon.SUBSCRIPTION} Подписки"
    UPCOMING = f"{Icon.CALENDAR} Списания"
    DEBTS = f"{Icon.DEBTS} Долги"
    ONE_TIME = f"{Icon.PAYMENT} Платёж"
    ADD_SUBSCRIPTION = f"➕ Подписка"
    SETTINGS = f"{Icon.SETTINGS} Настройки"


# ── Inline action labels ─────────────────────────────────────────────────────

class Action:
    EDIT = f"{Icon.EDIT} Изменить"
    PAUSE = f"{Icon.PAUSE} Приостановить"
    RESUME = f"{Icon.PLAY} Возобновить"
    DELETE = f"{Icon.TRASH} Удалить"
    CANCEL_ITEM = f"{Icon.TRASH} Отменить"
    BACK = f"{Icon.BACK} Назад"
    CONFIRM_DELETE = f"{Icon.TRASH} Да, удалить"
    CANCEL = "Отмена"
    CREATE = f"{Icon.CHECK} Создать"
    SAVE = "Сохранить"
    PAID = f"{Icon.CHECK} Оплачено"
    AMOUNT = f"{Icon.EDIT} Сумма"
    DATE = f"{Icon.CALENDAR} Дата"
    OPEN = f"{Icon.OPEN} Открыть"
    CONFIRM_CHARGE = f"{Icon.CHECK} Подтвердить списание"
    PROBLEM = f"{Icon.PROBLEM} Возникла проблема"
    CHARGED = CONFIRM_CHARGE  # backwards-compatible alias
    NOT_CHARGED = PROBLEM
    NO_MONEY = f"{Icon.NO_MONEY} Не хватило денег"
    DATE_CHANGED = f"{Icon.CALENDAR} Изменилась дата списания"
    PRICE_CHANGED = f"{Icon.PRICE_CHANGE} Изменилась стоимость"
    SUB_CANCELLED = f"{Icon.CANCEL_SUB} Подписка отменена"
    DELETE_SUB = f"{Icon.TRASH} Удалить подписку"
    SKIP = f"{Icon.SKIP} Пропустить"
    CANCEL_CROSS = f"{Icon.CROSS} Отмена"
    EDIT_AMOUNT = f"{Icon.EDIT} Изменить сумму"
    EDIT_DATE = f"{Icon.CALENDAR} Изменить дату"
    EDIT_RATE = f"{Icon.RATE} Изменить курс"
    RECALC_DEBTS = f"{Icon.DEBTS} Пересчитать долги"
    UNDO_CHARGE = f"{Icon.UNDO} Отменить списание"
    DELETE_CHARGE = f"{Icon.TRASH} Удалить списание"
    CONFIRM_UNDO = f"{Icon.UNDO} Да, отменить"
    NEW_METHOD = "➕ Новый способ"
    NEW_FRIEND = "➕ Новый друг"
    DONE = "Готово"
    NO_FRIENDS = "Без друзей"
    LATER = "Позже"
    YES = "Да"
    NO = "Нет"
    TODAY = f"🟢 {Copy.TODAY}"
    YESTERDAY = f"🟡 {Copy.YESTERDAY}"
    PICK_DATE = f"{Icon.CALENDAR} {Copy.PICK_DATE}"
    I_PAID = f"{Icon.CHECK} Я оплатил"
    PAY_LATER = f"{Icon.CLOCK} Оплачу позже"
    MONEY_RECEIVED = f"{Icon.CHECK} Деньги пришли"
    MONEY_NOT_RECEIVED = f"{Icon.CROSS} Деньги не пришли"
    CHECK_LATER = f"{Icon.CLOCK} Проверить позже"
    OPEN_DEBTS = f"{Icon.PEOPLE} Открыть долги"
    OPEN_PAYMENT = f"{Icon.HOTEL} Открыть платёж"
    HOME = f"{Icon.HOME} Главное меню"
    SHARE_LINK = "🔗 Ссылка для друга"
