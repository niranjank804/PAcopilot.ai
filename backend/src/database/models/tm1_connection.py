import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class TM1Connection(BaseModel, OrganizationScoped):
    __tablename__ = "tm1_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    address: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    port: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    ssl: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    encrypted_password: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # "native" (on-prem: address/port/user/password) or "v12_saas"
    # (PA as a Service: address/tenant/database + API key as password).
    authentication_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="native",
        server_default="native",
    )

    tenant: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    database: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # private: only its creator (created_by) sees and uses it — organization
    # admins can see and manage it, never use it. organization: every
    # member with the right permission, as before. src/tm1/service.py
    # enforces this in get_connection / list_connections.
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="private",
        server_default="private",
    )

    # dev | qa | prod — decides who may apply changes here
    # (src/tm1/governance.py).
    environment: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="dev",
        server_default="dev",
    )

    # Set when the TM1 server is inside a company network and is reached
    # through a PA-Copilot gateway there, instead of directly.
    gateway_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tm1_gateways.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Set by the platform owner (Super Admin) to stop all use of this
    # connection's credentials, whatever the organization's own settings.
    # Enforced where a TM1 session is opened (tm1/client/connection_manager).
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    suspended_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
