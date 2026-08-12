"""Machine-readable failure taxonomy for report executions.

Two rules this module exists to enforce:

1. Every failure carries a code from `ReportErrorCode`. A free-text
   message alone cannot be reasoned about — not by the retry policy, not
   by monitoring, and not by the person reading the execution history.

2. The retry decision is a property of the *code*, not of whoever caught
   the exception. `retry_class_for()` is the single source of truth, so a
   worker and the control plane cannot disagree about whether something
   is worth retrying.

The worker mirrors this enum (worker/pa_worker/errors.py) and sends codes
over the wire; `coerce_error_code()` is what stops an unknown or
attacker-supplied string from entering the system.
"""

from enum import Enum

from src.reports.enums import RetryClass


class ReportErrorCode(str, Enum):
    # --- Control plane / scheduling ---
    WORKER_OFFLINE = "worker_offline"
    WORKER_UNAUTHORIZED = "worker_unauthorized"
    WORKER_CAPABILITY_MISSING = "worker_capability_missing"
    DUPLICATE_JOB = "duplicate_job"
    EXECUTION_TIMEOUT = "execution_timeout"
    WORKER_LEASE_EXPIRED = "worker_lease_expired"
    CANCELLED = "cancelled"

    # --- Workbook custody ---
    WORKBOOK_MISSING = "workbook_missing"
    WORKBOOK_CHECKSUM_MISMATCH = "workbook_checksum_mismatch"
    WORKBOOK_INVALID = "workbook_invalid"
    WORKBOOK_TOO_LARGE = "workbook_too_large"

    # --- Excel / PAfE host ---
    EXCEL_LAUNCH_FAILED = "excel_launch_failed"
    EXCEL_CRASHED = "excel_crashed"
    PAFE_NOT_INSTALLED = "pafe_not_installed"
    PAFE_API_UNAVAILABLE = "pafe_api_unavailable"
    PAFE_VERSION_INCOMPATIBLE = "pafe_version_incompatible"
    WORKBOOK_OPEN_FAILED = "workbook_open_failed"

    # --- TM1 ---
    TM1_AUTH_FAILED = "tm1_auth_failed"
    TM1_CONNECTION_FAILED = "tm1_connection_failed"

    # --- Report production ---
    REFRESH_FAILED = "refresh_failed"
    EXPORT_FAILED = "export_failed"
    EXPORT_FORMAT_UNSUPPORTED = "export_format_unsupported"
    ARTIFACT_UPLOAD_FAILED = "artifact_upload_failed"

    # --- Delivery (Phase 5 — reserved, not produced today) ---
    EMAIL_FAILED = "email_failed"
    INVALID_RECIPIENT = "invalid_recipient"

    # --- Fallback ---
    INTERNAL_ERROR = "internal_error"


# Anything not listed is treated as NON_RETRYABLE by retry_class_for().
# That direction of default is deliberate: silently retrying a failure
# nobody has classified is how a broken job becomes a billing incident,
# whereas a non-retry is visible and a human can requeue it.
_RETRY_CLASSES: dict[ReportErrorCode, RetryClass] = {
    # Infrastructure that is expected to come back on its own.
    ReportErrorCode.WORKER_OFFLINE: RetryClass.RETRYABLE,
    ReportErrorCode.WORKER_LEASE_EXPIRED: RetryClass.RETRYABLE,
    ReportErrorCode.EXECUTION_TIMEOUT: RetryClass.RETRYABLE,
    ReportErrorCode.EXCEL_LAUNCH_FAILED: RetryClass.RETRYABLE,
    ReportErrorCode.EXCEL_CRASHED: RetryClass.RETRYABLE,
    ReportErrorCode.TM1_CONNECTION_FAILED: RetryClass.RETRYABLE,
    ReportErrorCode.ARTIFACT_UPLOAD_FAILED: RetryClass.RETRYABLE,
    ReportErrorCode.EMAIL_FAILED: RetryClass.RETRYABLE,
    # A refresh that failed against a reachable server is usually a data
    # or model problem, but TM1 also fails transiently under load; one
    # bounded set of retries is the lesser evil, and the attempt cap
    # stops it becoming a loop.
    ReportErrorCode.REFRESH_FAILED: RetryClass.RETRYABLE,
    ReportErrorCode.INTERNAL_ERROR: RetryClass.RETRYABLE,
    # Deterministic — the same input will fail the same way forever.
    ReportErrorCode.WORKBOOK_MISSING: RetryClass.NON_RETRYABLE,
    ReportErrorCode.WORKBOOK_CHECKSUM_MISMATCH: RetryClass.NON_RETRYABLE,
    ReportErrorCode.WORKBOOK_INVALID: RetryClass.NON_RETRYABLE,
    ReportErrorCode.WORKBOOK_TOO_LARGE: RetryClass.NON_RETRYABLE,
    ReportErrorCode.WORKBOOK_OPEN_FAILED: RetryClass.NON_RETRYABLE,
    ReportErrorCode.EXPORT_FORMAT_UNSUPPORTED: RetryClass.NON_RETRYABLE,
    ReportErrorCode.EXPORT_FAILED: RetryClass.NON_RETRYABLE,
    ReportErrorCode.DUPLICATE_JOB: RetryClass.NON_RETRYABLE,
    ReportErrorCode.CANCELLED: RetryClass.NON_RETRYABLE,
    # Retrying cannot fix these; a person has to change something.
    ReportErrorCode.TM1_AUTH_FAILED: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.INVALID_RECIPIENT: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.PAFE_NOT_INSTALLED: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.PAFE_API_UNAVAILABLE: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.PAFE_VERSION_INCOMPATIBLE: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.WORKER_UNAUTHORIZED: RetryClass.REQUIRES_HUMAN,
    ReportErrorCode.WORKER_CAPABILITY_MISSING: RetryClass.REQUIRES_HUMAN,
}


# What the end user is told. Never interpolate a driver message, a path, a
# URL or a credential into these — the raw detail goes to `diagnostics`,
# which is redacted and permission-gated.
_MESSAGES: dict[ReportErrorCode, str] = {
    ReportErrorCode.WORKER_OFFLINE: (
        "No online worker was available to run this report."
    ),
    ReportErrorCode.WORKER_UNAUTHORIZED: (
        "The worker is not authorized to run this report."
    ),
    ReportErrorCode.WORKER_CAPABILITY_MISSING: (
        # Covers both halves of the capability check — the PAfE add-in
        # and the export formats — because either can be the missing
        # piece and naming only one sends people to the wrong place.
        "No worker is able to run this report. Check that Planning "
        "Analytics for Microsoft Excel is installed on the worker and that "
        "it supports the requested output formats (run `pa-worker "
        "diagnostics` on the worker host)."
    ),
    ReportErrorCode.DUPLICATE_JOB: (
        "An execution for this occurrence already exists."
    ),
    ReportErrorCode.EXECUTION_TIMEOUT: (
        "The report did not finish within the configured time limit."
    ),
    ReportErrorCode.WORKER_LEASE_EXPIRED: (
        "The worker stopped responding while the report was running."
    ),
    ReportErrorCode.CANCELLED: "The execution was cancelled.",
    ReportErrorCode.WORKBOOK_MISSING: (
        "The workbook for this report could not be found."
    ),
    ReportErrorCode.WORKBOOK_CHECKSUM_MISMATCH: (
        "The downloaded workbook did not match its recorded checksum and "
        "was not opened."
    ),
    ReportErrorCode.WORKBOOK_INVALID: (
        "The uploaded file is not a valid Excel workbook."
    ),
    ReportErrorCode.WORKBOOK_TOO_LARGE: (
        "The workbook exceeds the maximum allowed size."
    ),
    ReportErrorCode.WORKBOOK_OPEN_FAILED: (
        "Excel could not open the workbook."
    ),
    ReportErrorCode.EXCEL_LAUNCH_FAILED: (
        "Microsoft Excel could not be started on the worker."
    ),
    ReportErrorCode.EXCEL_CRASHED: (
        "Microsoft Excel stopped responding while the report was running."
    ),
    ReportErrorCode.PAFE_NOT_INSTALLED: (
        "Planning Analytics for Microsoft Excel is not installed on the "
        "worker."
    ),
    ReportErrorCode.PAFE_API_UNAVAILABLE: (
        "The Planning Analytics for Microsoft Excel automation API could "
        "not be reached on the worker."
    ),
    ReportErrorCode.PAFE_VERSION_INCOMPATIBLE: (
        "The installed Planning Analytics for Microsoft Excel version is "
        "not supported."
    ),
    ReportErrorCode.TM1_AUTH_FAILED: (
        "Sign-in to the Planning Analytics server was rejected."
    ),
    ReportErrorCode.TM1_CONNECTION_FAILED: (
        "The Planning Analytics server could not be reached."
    ),
    ReportErrorCode.REFRESH_FAILED: (
        "The workbook refresh did not complete successfully."
    ),
    ReportErrorCode.EXPORT_FAILED: (
        "The report output could not be generated."
    ),
    ReportErrorCode.EXPORT_FORMAT_UNSUPPORTED: (
        "This workbook cannot be exported in one of the requested formats."
    ),
    ReportErrorCode.ARTIFACT_UPLOAD_FAILED: (
        "The generated report could not be uploaded."
    ),
    ReportErrorCode.EMAIL_FAILED: "The report could not be emailed.",
    ReportErrorCode.INVALID_RECIPIENT: (
        "One or more recipients are not valid."
    ),
    ReportErrorCode.INTERNAL_ERROR: (
        "The report failed for an unexpected reason."
    ),
}


def retry_class_for(code: ReportErrorCode) -> RetryClass:
    return _RETRY_CLASSES.get(code, RetryClass.NON_RETRYABLE)


def message_for(code: ReportErrorCode) -> str:
    return _MESSAGES.get(code, _MESSAGES[ReportErrorCode.INTERNAL_ERROR])


def coerce_error_code(value: str | None) -> ReportErrorCode:
    """Map a wire value onto the taxonomy, never trusting it.

    A worker is a customer-operated process, so what it posts is input,
    not truth. An unrecognised code becomes INTERNAL_ERROR rather than
    being stored verbatim — otherwise the error column becomes an
    unbounded free-text field that the retry policy silently defaults on.
    """

    if value is None:
        return ReportErrorCode.INTERNAL_ERROR

    try:
        return ReportErrorCode(value)
    except ValueError:
        return ReportErrorCode.INTERNAL_ERROR
