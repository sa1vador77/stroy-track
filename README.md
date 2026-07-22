# StroyTrack

[![CI](https://github.com/sa1vador77/stroy-track/actions/workflows/ci.yml/badge.svg)](https://github.com/sa1vador77/stroy-track/actions/workflows/ci.yml)

Сервис учёта строительных площадок для небольшой строительной компании.
Прорабы сдают ежедневные отчёты с объектов через Telegram-бота, офис видит
сводку по объектам на веб-дашборде: лента отчётов с фото, динамика численности
рабочих, расход материалов план/факт.

**Роли:** прораб (отчёты по своим объектам через бота) · менеджер (все объекты,
дашборд, справочники) · админ (управление пользователями).

**Стек:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL ·
aiogram 3 · APScheduler · Jinja2 + htmx · Docker Compose · uv · ruff · pytest

## Быстрый старт

```bash
cp .env.example .env
cp .env.bot.example .env.bot        # BOT_TOKEN выдаёт @BotFather
docker compose up --build
curl http://localhost:8000/health   # → {"status":"ok"}
```

Без `.env.bot` поднимутся API и база, а контейнер бота выйдет с подсказкой —
для работы с одним лишь API токен не нужен.

Первый администратор создаётся из консоли — в свежей базе некому выдать права через API:

```bash
docker compose exec app python -m app.cli create-admin --email admin@example.com
```

Swagger UI: http://localhost:8000/docs

## Архитектура

```mermaid
flowchart LR
    client["Клиент API<br/>(офис)"] -- "HTTPS + JWT" --> app
    tg["Telegram<br/>(прорабы)"] <-- "long polling" --> bot

    subgraph compose["Docker Compose"]
        app["app · FastAPI<br/>alembic upgrade head при старте"] --> pg[("PostgreSQL 17")]
        bot["bot · aiogram"] --> pg
    end
```

Всё приложение — один Python-пакет `app` и один Docker-образ. API, Telegram-бот
и планировщик напоминаний — отдельные процессы этого образа с общими моделями
и бизнес-логикой; в compose они различаются только командой запуска.
Фото из отчётов бот складывает в named volume `uploads`; в БД хранятся
только имена файлов.

```
app/
├── main.py       # сборка FastAPI-приложения
├── cli.py        # служебные команды: create-admin
├── core/         # конфиг, подключение к БД, безопасность, логирование
├── api/          # HTTP-слой: роутеры и зависимости (health, auth, users, sites,
│                 #             crews, materials, deliveries, reports)
├── bot/          # телеграм-бот прорабов: auth-middleware, /start,
│                 # диалог /report (работы, численность, материалы, фото)
├── models/       # SQLAlchemy-модели предметной области
└── schemas/      # Pydantic-схемы запросов и ответов
migrations/       # Alembic (async), автогенерация против моделей
tests/            # pytest: изолированная тестовая БД, httpx-клиент
```

## Схема БД

```mermaid
erDiagram
    users {
        int id PK
        string full_name
        string role "foreman | manager | admin"
        string email UK "вход в API (офис)"
        string password_hash "argon2; null у прорабов"
        bigint telegram_id UK "вход в бота (прораб)"
        bool is_active
    }
    construction_sites {
        int id PK
        string name
        string address
        date start_date
        date planned_end_date
        string status "active | suspended | completed"
    }
    crews {
        int id PK
        int site_id FK
        string name
        int size
    }
    materials {
        int id PK
        string name UK
        string unit
    }
    material_deliveries {
        int id PK
        int site_id FK
        int material_id FK
        numeric quantity
        date delivery_date
        string supplier
    }
    daily_reports {
        int id PK
        int site_id FK
        int foreman_id FK
        date report_date
        string work_description
        int workers_count
        timestamptz created_at
    }
    report_photos {
        int id PK
        int report_id FK
        string file_path
    }
    report_material_usages {
        int id PK
        int report_id FK
        int material_id FK
        numeric quantity
    }

    users }o--o{ construction_sites : site_assignments
    construction_sites ||--o{ crews : ""
    construction_sites ||--o{ material_deliveries : ""
    materials ||--o{ material_deliveries : ""
    construction_sites ||--o{ daily_reports : ""
    users ||--o{ daily_reports : ""
    daily_reports ||--o{ report_photos : ""
    daily_reports ||--o{ report_material_usages : ""
    materials ||--o{ report_material_usages : ""
```

Один отчёт прораба по объекту за день — `UNIQUE (site_id, foreman_id, report_date)`.
Каскады данных (`ON DELETE CASCADE`) — на стороне БД; справочники и авторы
отчётов защищены `RESTRICT`: историю нельзя удалить неявно.

## Разработка

```bash
uv sync                        # окружение и зависимости
docker compose up -d postgres  # БД для локального запуска и тестов
uv run alembic upgrade head    # схема дев-базы
uv run pytest                  # тесты (сами создают БД stroytrack_test)
uv run ruff check . && uv run ruff format --check .
```

Новая миграция после изменения моделей:

```bash
uv run alembic revision --autogenerate -m "описание"
```

Тесты ходят в настоящий PostgreSQL: каждый тест выполняется во внешней
транзакции с SAVEPOINT-ами и откатывается целиком, поэтому `commit()`
в коде приложения работает как в проде, а база между тестами чистая.
CI (GitHub Actions) гоняет линт, миграции, `alembic check` и тесты
на service-контейнере PostgreSQL.

## Архитектурные решения и почему

- **Один пакет, один образ, несколько процессов.** Микросервисы для системы
  такого размера — накладные расходы без выгоды; общие модели исключают
  дублирование, а процессы масштабируются независимо командой запуска.
- **uv вместо pip/poetry.** Детерминированные сборки через `uv.lock`, сам
  ставит нужный Python; в Dockerfile слой зависимостей кешируется отдельно
  от кода приложения.
- **DSN собирается из `POSTGRES_*`.** Те же переменные инициализируют контейнер
  postgres — один источник правды, рассинхрон учётных данных невозможен.
- **JWT: только access-токен, в токене один клейм `sub`.** Роль читается из БД
  на каждый запрос — смена прав и деактивация действуют мгновенно. Refresh-токенов
  нет: клиент — офисный веб, короткий TTL и перелогин дешевле лишнего контура.
- **pwdlib (argon2) + PyJWT.** Активно поддерживаемая связка, рекомендованная
  документацией FastAPI (passlib и python-jose заброшены). Верификация argon2 —
  CPU-bound, поэтому выполняется в тредпуле; при неизвестном email проверяется
  фиктивный хэш, чтобы время ответа не раскрывало базу адресов.
- **Fail-fast конфигурация.** С дефолтными `SECRET_KEY` или паролем БД приложение
  в prod-окружении не стартует; настройки валидируются pydantic-settings при запуске.
- **Enum'ы как VARCHAR, не нативный PG ENUM.** Новое значение статуса или роли
  не требует `ALTER TYPE` в миграции.
- **Naming convention для констрейнтов.** Имена индексов и ограничений
  детерминированы — autogenerate-миграции воспроизводимы, а тексты ошибок БД
  указывают на конкретное ограничение.
- **Тесты на реальном PostgreSQL, не SQLite.** Проверяется то, что поедет
  в прод: диалект, констрейнты, каскады. Изоляция — транзакцией, а не
  пересозданием схемы, поэтому весь прогон занимает пару секунд.
- **Миграции при старте контейнера.** `alembic upgrade head` перед uvicorn:
  одна реплика приложения — гонок за DDL нет, а окружение всегда на актуальной схеме.
- **`BOT_TOKEN` в отдельном `.env.bot`.** Общий `.env` попадает и в API-контейнер —
  токен бота там был бы лишним секретом; каждый процесс видит только свои ключи.
- **Бот тестируется без сети и моков Telegram-типов.** Фабрика сессий БД
  инжектируется в диспетчер (аналог `dependency_overrides` FastAPI), а исходящие
  вызовы Bot API перехватывает фейковая сессия; тесты скармливают апдейты
  через `feed_update` и проверяют ответы и записи в БД.
- **Отчёт пишется одной транзакцией на «Отправить».** Пока прораб отвечает
  на вопросы, данные копятся в FSM; в БД не бывает недозаполненных отчётов,
  а `/cancel` ничего не откатывает.
- **Фото скачиваются только при отправке отчёта.** До этого в FSM живут
  `file_id` из Telegram, поэтому брошенный или отменённый диалог не оставляет
  файлов на диске и чистить нечего.
- **`events_isolation` в диспетчере бота.** Альбом фото Telegram доставляет
  пачкой конкурентных апдейтов; без сериализации по чату каждый видел бы
  устаревшее состояние FSM — ломались бы лимиты и переходы диалога.

## Статус разработки

- [x] Скелет: Docker Compose, healthcheck, CI (ruff + pytest)
- [x] Модели домена, миграции Alembic, JWT-аутентификация и роли
- [x] CRUD API по сущностям с правами по ролям
- [x] Telegram-бот: диалог отчёта — работы, численность, материалы, фото
- [ ] Напоминания о несданных отчётах (APScheduler)
- [ ] Дашборд: карточки объектов, график численности, материалы план/факт
- [ ] Сводка за период и выгрузка в Excel
