import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class TM1Extraction(BaseModel, OrganizationScoped):
    """One metadata extraction of a connection, and what it found changed.

    The graph itself (tm1_objects, tm1_relationships) is rebuilt on every
    extraction and so only ever shows the model as it is now. These rows are
    its history: when the model was read, by whom or what, and which objects
    and dependencies appeared or disappeared since the extraction before —
    the answer to "what changed in the model since last week?".
    """

    __tablename__ = "tm1_extractions"

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

    # manual | schedule
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)

    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # succeeded | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationship_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_references: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # {"objects_added": [...], "objects_removed": [...],
    #  "relationships_added": [...], "relationships_removed": [...],
    #  "counts": {...}, "first": bool}. Lists are capped; counts are not.
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
