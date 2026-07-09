from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging(json_logs=get_settings().log_json)
    app = FastAPI(title="StroyTrack API", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
