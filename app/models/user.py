"""Пользователи и их роли."""

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum

if TYPE_CHECKING:
    from app.models.site import ConstructionSite


class UserRole(StrEnum):
    FOREMAN = "foreman"
    MANAGER = "manager"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str]
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole))
    # email + пароль — вход в API/дашборд (офис); telegram_id — вход в бота (прорабы)
    email: Mapped[str | None] = mapped_column(unique=True)
    password_hash: Mapped[str | None]
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    sites: Mapped[list["ConstructionSite"]] = relationship(
        secondary="site_assignments", back_populates="foremen"
    )
