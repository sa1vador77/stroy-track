"""site dates check constraint

Инвариант «плановое окончание не раньше начала» проверяет и API,
но от конкурентных PATCH защищает только ограничение в БД.
Написана руками: autogenerate не сравнивает CHECK-констрейнты.

Revision ID: d529baa80695
Revises: 349f0541606e
Create Date: 2026-07-11 23:17:55.001167

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d529baa80695"
down_revision: str | Sequence[str] | None = "349f0541606e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# имя короткое: полное ck_construction_sites_... собирает naming convention из metadata
_CONSTRAINT = "planned_end_not_before_start"


def upgrade() -> None:
    op.create_check_constraint(_CONSTRAINT, "construction_sites", "planned_end_date >= start_date")


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "construction_sites", type_="check")
