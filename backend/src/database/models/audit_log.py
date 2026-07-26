import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class AuditLog(BaseModel, OrganizationScoped):
    __tablename__ = "audit_logs"

    # organization_id is nullable only because it's SET NULL when the
    # owning org is hard-deleted (see the FK below) - not a "global" row
    # like Role's. No live session can legitimately belong to a deleted
    # org, so unlike Role this deliberately does NOT set
    # __tenant_nullable__ = True: NULL-org audit rows should never surface
    # from a live request's session.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    entity: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    old_values: Mapped[dict | None] = mapped_column(
        JSONB,
    )

    new_values: Mapped[dict | None] = mapped_column(
        JSONB,
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
    )
