import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class WorkItem(BaseModel, OrganizationScoped):
    """One piece of engineering work the team tracks: "PBI #1234: Workforce
    load fails on the new year".

    It holds no copies. Conversations and changes are linked to it
    (WorkItemLink), and its timeline is read from them, so it always shows
    what the records say now: the investigation, the proposed fix, who
    approved it, the deployment and its verification. People write the
    root cause and resolution; nothing fills them in automatically.
    """

    __tablename__ = "work_items"
    __table_args__ = (UniqueConstraint("organization_id", "reference", name="uq_work_items_org_reference"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The team's own reference, e.g. "PBI #1234" or "INC-88". Unique per organization.
    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open | in_progress | resolved | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class WorkItemLink(BaseModel, OrganizationScoped):
    """A conversation or a TM1 change attached to a work item."""

    __tablename__ = "work_item_links"
    __table_args__ = (UniqueConstraint("work_item_id", "kind", "target_id", name="uq_work_item_links_target"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # conversation | change
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # An ai_conversations or tm1_changes id. Not a foreign key: one column
    # serves both, and a deleted target shows as "no longer available".
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
