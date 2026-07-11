"""Служебные команды: python -m app.cli create-admin --email admin@example.com"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine, session_factory
from app.core.security import MIN_PASSWORD_LENGTH, hash_password
from app.models import User, UserRole


async def create_admin(session: AsyncSession, *, email: str, password: str, full_name: str) -> User:
    """Первый админ создаётся из консоли: в свежей базе некому выдать права через API."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль короче {MIN_PASSWORD_LENGTH} символов")
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ValueError(f"Пользователь с email {email} уже существует")
    admin = User(
        full_name=full_name,
        role=UserRole.ADMIN,
        email=email,
        password_hash=hash_password(password),
    )
    session.add(admin)
    await session.commit()
    return admin


async def _run_create_admin(args: argparse.Namespace) -> None:
    password = args.password or getpass.getpass("Пароль: ")
    async with session_factory() as session:
        admin = await create_admin(
            session, email=args.email, password=password, full_name=args.full_name
        )
    await engine.dispose()
    print(f"Админ создан: id={admin.id}, email={admin.email}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-admin", help="создать администратора")
    create.add_argument("--email", required=True)
    create.add_argument("--full-name", default="Администратор")
    create.add_argument("--password", help="если не указан — будет запрошен без эха")
    args = parser.parse_args()

    try:
        asyncio.run(_run_create_admin(args))
    except ValueError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
