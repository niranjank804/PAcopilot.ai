import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class AITask(BaseModel, OrganizationScoped):
    """Task memory: what one piece of engineering work in a conversation has
    established so far, so the next turn — typed or spoken — can say "fix it"
    and mean the thing found a moment ago.

    Distinct from the other two memories. The conversation (ai_messages) is
    what was said, in order. Engineering memory is approved, organization-wide
    knowledge. A task is the working state of one job: its objective, the
    TM1 objects it touched, findings, decisions, the changes drafted for it
    and where each is now. Nothing here becomes engineering memory unless a
    person asks and the existing approval runs.

    `state` holds the current, bounded picture the assistant is given; every
    change to it is also written to ai_task_events, which is append-only, so
    a later update never erases what was recorded before.
    """

    __tablename__ = "ai_tasks"
    __table_args__ = (
        Index("ix_ai_tasks_user_updated", "user_id", "updated_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | waiting_for_user | waiting_for_approval | blocked | completed
    # | failed | cancelled | archived
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Raised on every update; a writer that read an older version loses.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AITaskEvent(BaseModel, OrganizationScoped):
    """One recorded change to a task — append-only, never edited."""

    __tablename__ = "ai_task_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # created | objects | finding | decision | action | status | linked |
    # next_step | title | summarized
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # user | assistant | system
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
