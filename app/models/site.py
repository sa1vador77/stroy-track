from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, str_enum
from app.models.user import User

if TYPE_CHECKING:
    from app.models.crew import Crew


class SiteStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"


# Привязка прорабов к объектам (многие-ко-многим)
site_assignments = Table(
    "site_assignments",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    # PK(user_id, site_id) покрывает поиск только по user_id;
    # выборка «прорабы объекта» идёт по site_id
    Column(
        "site_id",
        ForeignKey("construction_sites.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


class ConstructionSite(Base):
    __tablename__ = "construction_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    address: Mapped[str]
    start_date: Mapped[date]
    planned_end_date: Mapped[date]
    status: Mapped[SiteStatus] = mapped_column(str_enum(SiteStatus), default=SiteStatus.ACTIVE)

    foremen: Mapped[list[User]] = relationship(secondary=site_assignments, back_populates="sites")
    # бригады удаляет ON DELETE CASCADE в БД: ORM их не подгружает
    # и не пытается занулить NOT NULL site_id
    crews: Mapped[list["Crew"]] = relationship(back_populates="site", passive_deletes=True)
