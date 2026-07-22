FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /srv/stroytrack

# Сначала только манифесты: слой с зависимостями кешируется отдельно от кода.
# Кэш uv живёт в cache mount и не раздувает слои образа.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/srv/stroytrack/.venv/bin:$PATH"

# работаем не от root; писать можно только в uploads/ — каталог создаётся
# и передаётся пользователю app заранее, потом прав на это уже нет
RUN groupadd -r app && useradd -r -g app app \
    && mkdir uploads && chown app:app uploads
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
