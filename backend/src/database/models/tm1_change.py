import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class TM1Change(BaseModel):
    """A proposed (and possibly executed) change to a TM1 artifact.

    Lifecycle: draft -> executed | failed -> rolled_back, or draft ->
    rejected (discarded without ever touching the live TM1 server).
    previous_content is the snapshot captured at execute time and is the
    rollback mechanism — TM1 has no object-level sandboxes.
    """

    __tablename__ = "tm1_changes"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tm1_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    change_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    target_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    new_content: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    previous_content: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    validation_errors: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    impact: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
