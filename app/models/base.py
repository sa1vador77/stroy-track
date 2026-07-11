"""Общее для всех моделей: naming convention констрейнтов, enum как VARCHAR."""

import enum

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase

# Явные шаблоны имён ограничений: без них PG генерирует имена сам,
# и autogenerate-миграции становятся невоспроизводимыми.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def str_enum(enum_cls: type[enum.StrEnum], length: int = 30) -> sa.Enum:
    """StrEnum как VARCHAR вместо нативного PG ENUM:
    новое значение не требует ALTER TYPE в миграции."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [member.value for member in e],
    )
