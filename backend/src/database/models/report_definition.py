import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportDefinition(BaseModel, OrganizationScoped):
    """What to run, against what, and in what shape.

    A definition on its own never fires. Execution comes from an explicit
    human "Run now" (gated by `reports.execute`) or, from Phase 3, from a
    schedule — and a schedule is what STET governs, because a schedule is
    the thing that can act without a person present.

    `connection_id` is nullable on purpose: IBM documents PAfE `Logon` as
    unable to sign in to cloud-hosted systems, so a large class of real
    deployments must rely on the interactive session or SSO already
    established on the worker rather than on credentials we hold. A null
    connection means "use the worker's existing PAfE session"; a non-null
    one means "sign in with these stored credentials first".
    """

    __tablename__ = "report_definitions"

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

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    report_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    workbook_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # RESTRICT, not CASCADE: deleting a workbook that reports depend on
        # should fail loudly rather than silently emptying those reports.
        ForeignKey("report_workbooks.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tm1_connections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Optional pin to a specific worker. Null means "any eligible worker
    # in this organization".
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Report-type-specific inputs (e.g. named ranges, sheet filters).
    # Never contains credentials — those resolve from connection_id at
    # dispatch time and are not stored here.
    parameters: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    output_formats: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Reserved for Phase 5. Present so adding delivery does not require
    # rewriting rows; `{}` means "produce artifacts, deliver nothing".
    delivery_configuration: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )

    # Reserved for Phase 6 (STET approval of schedules).
    approval_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_required",
        server_default="not_required",
    )
