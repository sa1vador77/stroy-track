# StroyTrack

Сервис учёта строительных площадок: прорабы сдают ежедневные отчёты через
Telegram-бота, офис видит сводку на веб-дашборде.

**Стек:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · aiogram 3 · Docker Compose

> Проект в разработке. Полное описание архитектуры и инструкции появятся по мере готовности.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health   # → {"status":"ok"}
```

Swagger UI: http://localhost:8000/docs

## Разработка

```bash
uv sync                        # окружение + зависимости (нужен uv)
docker compose up -d postgres  # база для локального запуска и тестов
uv run pytest                  # тесты
uv run ruff check . && uv run ruff format --check .  # линт
```
