import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportExecution(BaseModel, OrganizationScoped):
    """One attempt at producing one report.

    Immutable history: a retry is a *new* row pointing at the failed one
    through `parent_execution_id`, never a reopened terminal row. That is
    what makes "the retry must not send the email twice" enforceable —
    delivery state belongs to a row that can never re-enter RUNNING.

    `idempotency_key` is the duplicate-suppression mechanism. A scheduler
    tick that runs twice (restart, overlapping instance, retried job)
    computes the same key for the same occurrence and loses the race on a
    unique index rather than creating a second execution.

    `lease_expires_at` is how a crashed worker is detected. A worker holds
    a lease while ASSIGNED or RUNNING and extends it by heartbeating; once
    it lapses, the reaper can time the execution out and let a retry be
    created. Without it a worker that loses power leaves a job RUNNING
    forever.
    """

    __tablename__ = "report_executions"

    __table_args__ = (
        # Scoped to the organization, not global: two tenants computing
        # the same natural key for their own reports must not collide.
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_report_executions_org_idempotency_key",
        ),
        # The claim query's exact access path: eligible rows for one
        # organization, oldest first. Without it every poll from every
        # worker sequentially scans a table that only ever grows.
        Index(
            "ix_report_executions_claimable",
            "organization_id",
            "status",
            "available_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # RESTRICT so an execution history cannot be erased by deleting
        # the report it documents; report deletion archives instead.
        ForeignKey("report_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Snapshot of which workbook version this attempt used, so history
    # stays truthful after the report is re-pointed at a new workbook.
    workbook_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_workbooks.id", ondelete="SET NULL"),
        nullable=True,
    )

    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    trigger_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # Threaded through every log line on both sides of the wire so a run
    # can be followed from the API call to the Excel session and back.
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        index=True,
    )

    # The occurrence this execution represents (Phase 3). Null for manual
    # runs — those are "now", and "now" is not a schedulable slot.
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )

    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Timing ---

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Earliest time a worker may claim this. Exponential backoff for
    # retries is expressed here rather than by sleeping anywhere.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # --- Outcome ---

    error_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    retry_class: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # Redacted, structured detail for troubleshooting: step reached, host
    # facts, counts. Never credentials, connection strings or file paths.
    diagnostics: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # IBM PAfE automation TraceLog output, truncated. Gated behind
    # reports.read + org ownership like everything else on this row.
    trace_log: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
