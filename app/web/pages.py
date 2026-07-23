"""Страницы дашборда."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.web.deps import WebUser
from app.web.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index() -> RedirectResponse:
    """Корень сайта — это дашборд."""
    return RedirectResponse("/dashboard")


@router.get("/dashboard")
async def dashboard(request: Request, user: WebUser) -> Response:
    return templates.TemplateResponse(request, "dashboard.html", {"user": user})
