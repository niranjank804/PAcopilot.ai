import uuid

from sqlalchemy import (
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel


class UserRole(BaseModel):
    __tablename__ = "user_roles"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            name="uq_user_role",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
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

    user = relationship(
        "User",
        back_populates="user_roles",
    )

    role = relationship(
        "Role",
        back_populates="user_roles",
    )