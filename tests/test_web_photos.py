"""Тесты раздачи фото отчётов: авторизация, отдача байтов, оба вида 404."""

from pathlib import Path

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import company_today
from app.models import DailyReport, ReportPhoto
from tests.conftest import ReportFactory, SiteFactory, UserFactory
from tests.fake_telegram import FAKE_JPEG


def _put_file(upload_dir: Path, name: str, content: bytes = FAKE_JPEG) -> None:
    # общая фикстура каталог не создаёт (бот-тесты проверяют его отсутствие)
    upload_dir.mkdir(exist_ok=True)
    (upload_dir / name).write_bytes(content)


@pytest.fixture
async def photo(
    db_session: AsyncSession,
    make_user: UserFactory,
    make_site: SiteFactory,
    make_report: ReportFactory,
) -> ReportPhoto:
    foreman = await make_user(telegram_id=1)
    site = await make_site(foremen=[foreman])
    report: DailyReport = await make_report(site, foreman, report_date=company_today())
    row = ReportPhoto(report_id=report.id, file_path="a1b2c3.jpg")
    db_session.add(row)
    await db_session.commit()
    return row


class TestPhotoServing:
    async def test_photo_bytes_served(
        self, office: AsyncClient, photo: ReportPhoto, upload_dir: Path
    ):
        _put_file(upload_dir, photo.file_path)

        response = await office.get(f"/dashboard/photos/{photo.id}")

        assert response.status_code == 200
        assert response.content == FAKE_JPEG
        assert response.headers["content-type"] == "image/jpeg"
        # имя файла — uuid: контент по URL неизменен, кеш только приватный
        assert response.headers["cache-control"] == "private, max-age=31536000, immutable"

    async def test_unknown_id_404(self, office: AsyncClient, upload_dir: Path):
        response = await office.get("/dashboard/photos/999999")

        assert response.status_code == 404

    async def test_missing_file_404_with_warning(
        self, office: AsyncClient, photo: ReportPhoto, upload_dir: Path
    ):
        """Запись в БД есть, файла на диске нет — не 500 и след в логах."""
        with structlog.testing.capture_logs() as logs:
            response = await office.get(f"/dashboard/photos/{photo.id}")

        assert response.status_code == 404
        [event] = [entry for entry in logs if entry["event"] == "report_photo_missing"]
        assert event["photo_id"] == photo.id
        assert event["log_level"] == "warning"

    async def test_file_path_cannot_escape_upload_dir(
        self,
        office: AsyncClient,
        db_session: AsyncSession,
        photo: ReportPhoto,
        upload_dir: Path,
        tmp_path: Path,
    ):
        """Барьер на данные: «../x» в file_path не выводит чтение за каталог фото."""
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"top-secret")
        photo.file_path = "../secret.txt"
        await db_session.commit()

        with structlog.testing.capture_logs() as logs:
            response = await office.get(f"/dashboard/photos/{photo.id}")

        assert response.status_code == 404
        assert b"top-secret" not in response.content
        [event] = [e for e in logs if e["event"] == "report_photo_outside_upload_dir"]
        assert event["photo_id"] == photo.id

    async def test_requires_auth(self, client: AsyncClient, photo: ReportPhoto, upload_dir: Path):
        _put_file(upload_dir, photo.file_path)

        response = await client.get(f"/dashboard/photos/{photo.id}")

        assert response.status_code == 303
        assert response.headers["location"].startswith("/dashboard/login")
