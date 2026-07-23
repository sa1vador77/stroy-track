"""Раздача фотографий из отчётов."""

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.deps import PathID, SessionDep
from app.core.config import get_settings
from app.models import ReportPhoto
from app.web.deps import WebUser

router = APIRouter(prefix="/dashboard", include_in_schema=False)

log = structlog.get_logger()


@router.get("/photos/{photo_id}")
async def report_photo(photo_id: PathID, _: WebUser, session: SessionDep) -> Response:
    """Фото по id из БД: имя файла с диска извне не принимается."""
    photo = await session.get(ReportPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    base = get_settings().upload_dir
    path = base / photo.file_path
    # барьер на сами данные: бот пишет голые uuid-имена, но «/abs» или «../x»
    # в file_path вывели бы чтение за каталог фото — Path("a") / "/b" == "/b"
    if not path.resolve().is_relative_to(base.resolve()):
        log.warning("report_photo_outside_upload_dir", photo_id=photo.id, file_path=photo.file_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        # файл читается целиком: фото Telegram — сотни КБ, Range ни к чему.
        # FileResponse не годится: свой stat он делает уже после выхода из
        # хендлера и на исчезнувшем файле падает 500 — а бот удаляет старые
        # файлы при замене отчёта; открытие файла закрывает окно «проверил-отдал»
        content = await run_in_threadpool(path.read_bytes)
    except OSError:
        # запись есть, файла нет: не примонтирован том или файл удалили руками
        log.warning("report_photo_missing", photo_id=photo.id, file_path=photo.file_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    # имя файла — uuid, контент по этому URL не меняется никогда; private —
    # фото за cookie-гейтом, общим кешам его хранить нельзя
    return Response(
        content,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
