import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class Role(BaseModel, OrganizationScoped):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_role_org_name",
        ),
    )

    # NULL organization_id = a global/system role, shared across every
    # organization (e.g. the seeded Super Admin/Analyst/Viewer roles) - the
    # tenancy filter must keep these visible from any org's session, not
    # just the row's own org.
    __tenant_nullable__ = True

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
    )

    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    organization = relationship(
        "Organization",
        back_populates="roles",
    )

    user_roles = relationship(
        "UserRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )

    role_permissions = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
    )