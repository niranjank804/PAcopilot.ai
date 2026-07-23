from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from  ..base import BaseModel


class Organization(BaseModel):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users = relationship(
        "User",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    roles = relationship(
        "Role",
        back_populates="organization",
        cascade="all, delete-orphan",
    )