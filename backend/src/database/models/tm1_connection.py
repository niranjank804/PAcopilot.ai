import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class TM1Connection(BaseModel):
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
