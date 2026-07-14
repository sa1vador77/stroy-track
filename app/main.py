"""Сборка FastAPI-приложения и его жизненный цикл."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.crews import router as crews_router
from app.api.deliveries import router as deliveries_router
from app.api.health import router as health_router
from app.api.materials import router as materials_router
from app.api.reports import router as reports_router
from app.api.sites import router as sites_router
from app.api.users import router as users_router
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
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(sites_router)
    app.include_router(crews_router)
    app.include_router(materials_router)
    app.include_router(deliveries_router)
    app.include_router(reports_router)
    return app


app = create_app()
