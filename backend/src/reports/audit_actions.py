"""Audit action names for report automation.

An enum rather than string literals scattered across routers: the audit
log is queried by action name, so a typo in one call site silently
creates a second, near-identical action that no report or alert matches.

Naming follows the existing convention in this codebase (see the TM1
router's audit calls): UPPER_SNAKE, resource first, past-tense verb last.
"""

from enum import Enum


class ReportAuditAction(str, Enum):
    # Workbooks
    WORKBOOK_UPLOADED = "REPORT_WORKBOOK_UPLOADED"
    WORKBOOK_DELETED = "REPORT_WORKBOOK_DELETED"

    # Report definitions
    REPORT_CREATED = "REPORT_CREATED"
    REPORT_UPDATED = "REPORT_UPDATED"
    REPORT_ARCHIVED = "REPORT_ARCHIVED"

    # Executions
    EXECUTION_CREATED = "REPORT_EXECUTION_CREATED"
    EXECUTION_CLAIMED = "REPORT_EXECUTION_CLAIMED"
    EXECUTION_STARTED = "REPORT_EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "REPORT_EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "REPORT_EXECUTION_FAILED"
    EXECUTION_CANCELLED = "REPORT_EXECUTION_CANCELLED"
    EXECUTION_RETRY_SCHEDULED = "REPORT_EXECUTION_RETRY_SCHEDULED"

    # Artifacts
    ARTIFACT_CREATED = "REPORT_ARTIFACT_CREATED"

    # Workers
    WORKER_REGISTERED = "REPORT_WORKER_REGISTERED"
    WORKER_ENROLLED = "REPORT_WORKER_ENROLLED"
    WORKER_ENROLLMENT_REISSUED = "REPORT_WORKER_ENROLLMENT_REISSUED"
    WORKER_CREDENTIAL_ROTATED = "REPORT_WORKER_CREDENTIAL_ROTATED"
    WORKER_DISABLED = "REPORT_WORKER_DISABLED"
    WORKER_ENABLED = "REPORT_WORKER_ENABLED"
