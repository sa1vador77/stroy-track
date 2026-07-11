"""Живость сервиса — для healthcheck'ов Docker и мониторинга."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep

router = APIRouter()


@router.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    """Живость сервиса и доступность БД; 503 — база не отвечает."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ok"}
