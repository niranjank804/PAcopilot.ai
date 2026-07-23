import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # "pending" | "approved" | "rejected" — separate from is_active, which
    # is for an admin disabling an already-approved account. Existing rows
    # (created before self-registration existed) default to "approved" via
    # server_default so this migration doesn't lock anyone out.
    registration_status: Mapped[str] = mapped_column(
        String(20),
        default="approved",
        server_default="approved",
        nullable=False,
    )

    organization = relationship(
        "Organization",
        back_populates="users",
    )
    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )