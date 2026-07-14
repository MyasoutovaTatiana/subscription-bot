# PROJECT_CONTEXT

Документ передачи контекста для нового чата. Сверен с кодом репозитория `subscription-bot` (состояние на момент создания docs).

## Что делает проект

Telegram-бот для **личного** учёта:

- регулярных подписок и ближайших списаний;
- разовых валютных платежей;
- деления трат с друзьями (контакты создаются вручную, друзья **не** обязаны запускать бота);
- долгов вида **«мне должны»** (друг → владелец аккаунта).

Управление только через Telegram: сообщения, reply-клавиатура, inline-кнопки. Веб-админки нет.

## Основные пользовательские сценарии


| Сценарий                                    | Вход                                          | Статус в коде                                                   |
| ------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------- |
| Онбординг                                   | `/start` → дашборд + reply-меню               | Реализовано                                                     |
| Новая подписка                              | «➕ Подписка» / FSM                            | Реализовано (друзья на шаге — пропуск)                          |
| Список / карточка / pause / delete / edit   | «💳 Подписки»                                 | Реализовано                                                     |
| Ближайшие списания                          | «📅 Списания» · 7 / 30 / все                  | Реализовано                                                     |
| Разовый платёж + деление поровну            | «💸 Платёж»                                   | Реализовано (UI: equal; percent/fixed — в сервисе)              |
| Долги «кто мне должен»                      | «👥 Долги»                                    | Реализовано                                                     |
| Настройки                                   | TZ, время уведомлений, карты, друзья, wipe ×2 | Частично (экспорт — заглушка)                                   |
| Напоминания о списании                      | APScheduler job                               | Реализовано                                                     |
| Подтверждение списания                      | callback из напоминания                       | Confirm сразу; проблема → сценарии              |
| «Возникла проблема»                         | callbacks                                     | Дата / сумма / пауза / удаление                 |
| Подтверждение оплаты другом                 | deep-link `debt_<token>`                      | Двухэтапное (друг → владелец)                   |


**Не реализовано как продуктовый сценарий (подтверждено кодом):**

- раздел **«я должен»** (обратные обязательства владельца);
- банк / SMS / Gmail / AI / веб-админка.

## Архитектура и стек

```text
Telegram handlers / keyboards / states / ui
        ↓
Services (бизнес-логика, без отправки в TG*)
        ↓
Repositories (SQLAlchemy async)
        ↓
Models + SQLite / PostgreSQL (DATABASE_URL)
```

 Исключение: `app/scheduler/jobs.py` отправляет напоминания через `Bot.send_message` (адаптер у job, не у «чистого» сервиса планирования).


| Слой       | Технологии                                                  |
| ---------- | ----------------------------------------------------------- |
| Runtime    | Python 3.12+ (локально также прогонялось на 3.14)           |
| Bot        | aiogram 3                                                   |
| DB         | SQLAlchemy 2 async, aiosqlite / asyncpg                     |
| Migrations | Alembic (`20fb5ceb0ab9` initial + `a1b2c3d4e5f6` debt review) |
| Config     | pydantic-settings                                           |
| HTTP FX    | httpx → CBR XML                                             |
| Jobs       | APScheduler AsyncIOScheduler                                |
| Money      | `Decimal` / `Numeric` (не float)                            |
| TZ         | `zoneinfo`                                                  |
| UI         | `app/ui` (UI Kit) + HTML parse mode                         |
| Tests      | pytest, pytest-asyncio                                      |
| Deploy     | Dockerfile, docker-compose.yml                              |


**Запуск:** `python -m app.main`  
При старте: валидация settings → engine → `create_all` (+ ожидаются миграции) → scheduler → polling → shutdown scheduler/bot/engine.

**DI:** `DbSessionMiddleware` (session на update) + `UserMiddleware` (get_or_create user).

## Ключевые сущности и связи

```text
User 1──* PaymentMethod
User 1──* Subscription ──? PaymentMethod
Subscription 1──* SubscriptionParticipant ── Friend
User 1──* Friend
User 1──* Transaction ──? Subscription
Transaction 1──* TransactionSplit ──? Friend
Transaction 1──* Debt ── Friend
User 1──* ReminderDelivery ── Subscription
ExchangeRate (кэш курсов, без user_id)
```

**Debt** в модели и docstring — «деньги, которые **друг должен** пользователю» (`amount_rub`, `status`: active/paid/cancelled). Обратного «я должен» в схеме нет.

**Деньги:** `original_`* + `estimated_rub_amount` + optional `actual_rub_amount`; для долгов предпочитается actual, иначе estimated (`is_estimated`).

## Структура проекта (актуально)

```text
app/
  main.py, bot.py, config.py, logging_setup.py
  handlers/          # start, subscriptions, one_time, upcoming, debts, settings, cancel
  keyboards/         # main_menu, subscriptions, payments, debts
  states/            # subscriptions, payments
  models/            # ORM + enums
  repositories/
  services/          # subscriptions, transactions, charges, currency, billing_dates,
                     # debt_calculator, reminders, subscription_cards, exchange_rates/
  scheduler/         # setup + jobs
  middlewares/       # db, user
  database/          # engine, session
  ui/                # UI Kit (tokens, text, money, status, feedback, card, buttons, home)
  utils/             # money, dates, telegram, callback_data
alembic/
tests/
docs/                # эта папка
Dockerfile, docker-compose.yml, README.md, pyproject.toml, requirements.txt
.env.example
```

Cursor rule UI: `.cursor/rules/telegram-ui-kit.mdc`.

## Команды запуска

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # задать BOT_TOKEN (см. STATUS — проверка секрета!)
alembic upgrade head
python -m app.main
pytest
docker compose up --build
```

Переменные (ожидаемые): `BOT_TOKEN`, `DATABASE_URL`, `TIMEZONE`, `DEFAULT_REMINDER_TIME`, `SCHEDULER_INTERVAL_MINUTES`, `LOG_LEVEL`.

PostgreSQL: `DATABASE_URL=postgresql+asyncpg://...` — URL поддерживается кодом engine; **полный e2e на PG в репозитории не зафиксирован тестами** (см. STATUS).

## Важные технические ограничения

1. Нет банковских интеграций и автосписаний.
2. Курсы — официальный XML CBR через `CbrExchangeRateProvider` + кэш; без курса из будущего; fallback на последний сохранённый ≤ даты.
3. Один periodic job напоминаний (не per-subscription jobs); идемпотентность через `reminder_deliveries.unique_key`.
4. Multi-user: данные фильтруются по `user_id` / telegram id (архитектура готова; продукт «личный»).
5. UI только на русском; HTML + escape пользовательского ввода.
6. Бизнес-сервисы не должны слать сообщения в Telegram (кроме scheduler adapter).
7. Новые экраны — через `app/ui`, не ad-hoc разметка (правило UI Kit).
8. `main.py` дополнительно вызывает `Base.metadata.create_all` при старте — удобно для MVP; для прод предпочтительны миграции Alembic.
9. Memory FSM storage — сценарии сбрасываются при рестарте процесса.

## Неподтверждённые факты

- Реальный пользовательский прогон всех FSM в Telegram **в docs не зафиксирован** (тесты покрывают calculators/FX/reminders/UI kit, не e2e Bot API).
- Поведение CBR в праздники — логика «искать назад до 10 дней» есть в коде; полный перечень праздников не моделируется отдельно.

