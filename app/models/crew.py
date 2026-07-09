from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.site import ConstructionSite


class Crew(Base):
    __tablename__ = "crews"
    __table_args__ = (CheckConstraint("size > 0", name="size_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    site_id: Mapped[int] = mapped_column(
        ForeignKey("construction_sites.id", ondelete="CASCADE"), index=True
    )
    size: Mapped[int]

    site: Mapped[ConstructionSite] = relationship(back_populates="crews")
