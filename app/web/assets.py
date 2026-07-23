"""Статика дашборда: vendored-библиотеки с вечным кешем."""

from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope


class WebStatic(StaticFiles):
    """StaticFiles с Cache-Control для vendor-файлов.

    Starlette из коробки отдаёт только ETag/Last-Modified — браузер
    ревалидирует каждый ассет на каждой навигации MPA. Версия библиотеки
    зашита в имя каталога, обновление меняет URL, поэтому immutable безопасен.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.startswith("vendor/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_static() -> WebStatic:
    return WebStatic(directory=Path(__file__).parent / "static")
