# Subscription Bot

Telegram-бот для личного учёта регулярных подписок, будущих списаний, разовых валютных платежей и долгов друзей. Весь интерфейс — внутри Telegram (сообщения, reply-клавиатура, inline-кнопки). Веб-админки нет.

## Документация для продолжения работы

- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — контекст и архитектура
- [docs/PRODUCT_RULES.md](docs/PRODUCT_RULES.md) — бизнес-правила
- [docs/STATUS.md](docs/STATUS.md) — что готово / риски
- [docs/TASKS.md](docs/TASKS.md) — бэклог
- [docs/ROADMAP.md](docs/ROADMAP.md) — согласованный порядок релизов
- [docs/DECISIONS.md](docs/DECISIONS.md) — принятые решения

## Возможности

- Регулярные подписки с категориями, валютами и способами оплаты
- Напоминания за N дней до списания (APScheduler)
- Ориентировочный перевод в рубли по курсу ЦБ РФ
- Разовые платежи с делением между друзьями
- Список долгов и отметка оплаченных
- Ближайшие списания (7 / 30 дней / все)
- Настройки: часовой пояс, время уведомлений, карты, друзья, удаление данных

## Технологии

- Python 3.12+
- aiogram 3
- SQLAlchemy 2 (async) + aiosqlite / asyncpg
- Alembic
- APScheduler
- httpx
- pydantic-settings
- pytest / pytest-asyncio

## Структура

```text
app/
  main.py              # точка входа
  config.py
  bot.py
  handlers/            # Telegram UI
  keyboards/
  states/
  models/
  repositories/
  services/            # бизнес-логика (без отправки в Telegram)
  scheduler/
  utils/
  database/
tests/
alembic/
```

## Требования

- Python 3.12 или новее
- Токен бота от [@BotFather](https://t.me/BotFather)

## Создание бота в BotFather

1. Открой [@BotFather](https://t.me/BotFather)
2. Команда `/newbot`
3. Задай имя и username
4. Скопируй токен вида `123456:ABC...`

## Локальная установка

```bash
cd subscription-bot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Отредактируй `.env` и вставь `BOT_TOKEN`.

### Переменные окружения

```env
BOT_TOKEN=
DATABASE_URL=sqlite+aiosqlite:///./subscription_bot.db
TIMEZONE=Europe/Moscow
DEFAULT_REMINDER_TIME=10:00
SCHEDULER_INTERVAL_MINUTES=10
LOG_LEVEL=INFO
```

## Миграции

```bash
alembic upgrade head
```

При первом запуске `python -m app.main` также создаёт таблицы через `create_all` (удобно для MVP). Для продакшена опирайся на Alembic.

## Запуск

```bash
python -m app.main
```

После старта открой бота в Telegram и отправь `/start`.

## Тесты

```bash
pytest
```

## Docker

```bash
cp .env.example .env   # укажи BOT_TOKEN
mkdir -p data
docker compose up --build -d
docker compose logs -f bot
```

База SQLite будет в `./data/subscription_bot.db`.

## Резервное копирование

SQLite:

```bash
cp subscription_bot.db backup_$(date +%F).db
# или для Docker-volume:
cp data/subscription_bot.db backup_$(date +%F).db
```

PostgreSQL: обычный `pg_dump`.

## Переход на PostgreSQL

1. Подними PostgreSQL
2. В `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/subscription_bot
```

1. Выполни `alembic upgrade head`
2. Перезапусти бота

Бизнес-логика менять не нужно — достаточно `DATABASE_URL`.

## Типовые ошибки

| Проблема                     | Что проверить                                                                |
| ---------------------------- | ---------------------------------------------------------------------------- |
| `ValidationError` при старте | Заполнен ли `BOT_TOKEN` в `.env`                                             |
| Бот не отвечает              | Токен, интернет, не запущен ли второй инстанс с тем же токеном               |
| Нет курса валюты             | Сеть до `cbr.ru`, позже — кэш в таблице `exchange_rates`                     |
| Напоминания не приходят      | Часовой пояс пользователя, `reminder_time`, offsets подписки, логи scheduler |

## Безопасность

- Не коммить `.env` и файлы БД
- Не храни номер карты / CVV / банковские пароли — только названия способов оплаты
- Токен BotFather держи в секрете
- Для нескольких пользователей данные изолированы по `user_id`

## Ограничения MVP

Не реализовано и не планируется в этой версии:

- интеграции с банками / SMS / Gmail
- автоматическое списание и встроенная оплата
- веб-админка и графики аналитики
- AI-функции
- платная подписка на самого бота

## Деление сумм (правило копеек)

При делении поровну остаток копеек после округления добавляется к доле **владельца** платежа. Если владелец не участвует в делении — к **последнему** участнику. Сумма долей всегда равна общей сумме.

## Лицензия

Личный проект / MVP.
