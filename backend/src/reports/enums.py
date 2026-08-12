"""Every state string in the report automation domain, in one place.

Persisted as plain strings (matching the rest of this codebase, which
stores `status` as String rather than a native PG enum so a new state
never needs a type migration), but the *only* legitimate way to produce
one of those strings is a member of one of these enums.
"""

from enum import Enum


class ReportType(str, Enum):
    """What kind of engine produces this report.

    Only PAFE_WORKBOOK is implemented. The rest are reserved so the
    runner abstraction and the database column do not need to change when
    the native TM1 engine lands (Phase 8) — they are rejected at
    validation time today.
    """

    PAFE_WORKBOOK = "pafe_workbook"

    # Reserved — not implemented. See docs/report-automation/ARCHITECTURE.md.
    TM1_NATIVE = "tm1_native"
    MDX_REPORT = "mdx_report"
    QUICK_REPORT = "quick_report"
    EXPLORATION = "exploration"
    DYNAMIC_REPORT = "dynamic_report"
    CUSTOM_REPORT = "custom_report"


IMPLEMENTED_REPORT_TYPES = frozenset({ReportType.PAFE_WORKBOOK})


class ReportStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ApprovalStatus(str, Enum):
    """STET governance state.

    Reserved for Phase 6, where *schedules* — the thing that can fire
    without a human in the loop — enter STET_REVIEW before they can
    activate. A report definition on its own executes nothing, so today
    every row is NOT_REQUIRED and the column exists to avoid a second
    migration later.
    """

    NOT_REQUIRED = "not_required"
    DRAFT = "draft"
    STET_REVIEW = "stet_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class OutputFormat(str, Enum):
    XLSX = "xlsx"
    PDF = "pdf"
    CSV = "csv"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


TERMINAL_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.CANCELLED,
    }
)

# Statuses a worker holds a lease on. An execution stuck in one of these
# past its lease is how a crashed worker is detected — see
# execution_service.reap_stale_executions().
LEASED_EXECUTION_STATUSES = frozenset(
    {
        ExecutionStatus.ASSIGNED,
        ExecutionStatus.RUNNING,
    }
)


class TriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RETRY = "retry"


class WorkerStatus(str, Enum):
    # Created in the console, has not completed enrollment yet — holds an
    # enrollment token but no credential, so it cannot authenticate.
    PENDING_ENROLLMENT = "pending_enrollment"
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    DISABLED = "disabled"
    ERROR = "error"


# A worker in any other status must not be issued a token or handed a job.
WORKER_SCHEDULABLE_STATUSES = frozenset(
    {
        WorkerStatus.ONLINE,
        WorkerStatus.BUSY,
        WorkerStatus.OFFLINE,
    }
)


class WorkerCapability(str, Enum):
    """Verified host facts, not aspirations.

    The worker only reports a capability its `doctor` probe actually
    confirmed on that machine (Excel responds to COM, the PAfE COM add-in
    loads and exposes the automation object, Excel can export a PDF).
    The control plane refuses to schedule work that needs a capability
    the assigned worker never proved.
    """

    EXCEL = "excel"
    PAFE_AUTOMATION = "pafe_automation"
    XLSX_EXPORT = "xlsx_export"
    PDF_EXPORT = "pdf_export"
    CSV_EXPORT = "csv_export"


# Which capability each output format needs on the executing worker.
FORMAT_CAPABILITY = {
    OutputFormat.XLSX: WorkerCapability.XLSX_EXPORT,
    OutputFormat.PDF: WorkerCapability.PDF_EXPORT,
    OutputFormat.CSV: WorkerCapability.CSV_EXPORT,
}


class RetryClass(str, Enum):
    """How a failure should be treated, decided once at the point of
    failure rather than re-guessed by every caller."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    REQUIRES_HUMAN = "requires_human"
