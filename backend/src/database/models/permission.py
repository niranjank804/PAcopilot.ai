from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel


class Permission(BaseModel):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
    )

    role_permissions = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
    )
