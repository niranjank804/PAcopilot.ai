import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class EngineeringMemory(BaseModel, OrganizationScoped):
    """One thing the team knows about its TM1 model that the model itself
    cannot say: "Process X must run after Process Y", "do not change rule Z
    without the controller's sign-off", "this cube has a known feeder issue".

    Approved memories are given to the assistant in every conversation,
    marked as organization knowledge. Nothing the assistant writes becomes
    one by itself: its suggestions are `proposed` until a person with
    knowledge.write approves them. Every edit is a new version
    (`supersedes`), so what the assistant was told, and when, is never lost.
    """

    __tablename__ = "engineering_memories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Org-wide when null; otherwise about one TM1 server.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Optional: the object it is about (cube / dimension / process / chore / rule).
    object_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    object_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # convention | sequence | caution | known_issue | note
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # proposed | approved | rejected | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # human | ai
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # The version this one replaced (edits never overwrite).
    supersedes: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engineering_memories.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Why the assistant proposed it: the evidence it saw.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
