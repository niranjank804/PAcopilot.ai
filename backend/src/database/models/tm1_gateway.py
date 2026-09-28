import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class TM1Gateway(BaseModel, OrganizationScoped):
    """A PA-Copilot gateway: a small program inside a company network that
    carries TM1 requests between this backend and the TM1 servers there.

    Installed once per network, not per TM1 server. It connects out, so
    the network's firewall stays closed. Its key is shown once when the
    gateway is created (or its key rotated) and stored only as an HMAC
    digest keyed with SECRET_KEY — the same scheme as report workers.
    """

    __tablename__ = "tm1_gateways"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Bumped on rotation: a key from before stops working at once.
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # When the gateway last asked for work; "online" is derived from it.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # What the gateway reported about itself on its last poll.
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
