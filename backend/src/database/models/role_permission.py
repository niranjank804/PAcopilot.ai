import uuid

from sqlalchemy import (
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel


class RolePermission(BaseModel):
    __tablename__ = "role_permissions"

    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "permission_id",
            name="uq_role_permission",
        ),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "roles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "permissions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role = relationship(
        "Role",
        back_populates="role_permissions",
    )

    permission = relationship(
        "Permission",
        back_populates="role_permissions",
    )
