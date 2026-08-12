"""Worker-side mirror of the control plane's error taxonomy.

These strings must match `backend/src/reports/errors.py` exactly. The
control plane coerces anything it does not recognise to
`internal_error`, so a drift here does not create a security hole — it
creates a *diagnostic* hole, where a specific, actionable failure gets
reported as "unexpected". The test suite asserts the two enums agree.

`WorkerError` carries the code, so the failure classification is decided
where the failure actually happens rather than being re-inferred from an
exception message further up the stack.
"""

from enum import Enum


class WorkerErrorCode(str, Enum):
    # Workbook custody
    WORKBOOK_MISSING = "workbook_missing"
    WORKBOOK_CHECKSUM_MISMATCH = "workbook_checksum_mismatch"
    WORKBOOK_INVALID = "workbook_invalid"
    WORKBOOK_TOO_LARGE = "workbook_too_large"
    WORKBOOK_OPEN_FAILED = "workbook_open_failed"

    # Excel / PAfE host
    EXCEL_LAUNCH_FAILED = "excel_launch_failed"
    EXCEL_CRASHED = "excel_crashed"
    PAFE_NOT_INSTALLED = "pafe_not_installed"
    PAFE_API_UNAVAILABLE = "pafe_api_unavailable"
    PAFE_VERSION_INCOMPATIBLE = "pafe_version_incompatible"

    # TM1
    TM1_AUTH_FAILED = "tm1_auth_failed"
    TM1_CONNECTION_FAILED = "tm1_connection_failed"

    # Report production
    REFRESH_FAILED = "refresh_failed"
    EXPORT_FAILED = "export_failed"
    EXPORT_FORMAT_UNSUPPORTED = "export_format_unsupported"
    ARTIFACT_UPLOAD_FAILED = "artifact_upload_failed"

    # Lifecycle
    EXECUTION_TIMEOUT = "execution_timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class WorkerError(Exception):
    """A failure with a machine-readable classification attached.

    `detail` is for the worker's own log and for the `diagnostics` blob.
    It must never contain a credential, a full path, or a raw COM error
    string that might embed either — `redact()` in logging.py is applied
    before anything leaves the process.
    """

    def __init__(
        self,
        code: WorkerErrorCode,
        message: str,
        *,
        detail: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.detail = detail or {}

        super().__init__(f"{code.value}: {message}")


class ControlPlaneError(Exception):
    """PA-Copilot was unreachable or answered with an error.

    Deliberately distinct from WorkerError: this is a failure to *report*
    a result, not a failure to produce one. The difference matters — a
    successful refresh followed by an unreachable API must not be
    recorded as a failed report.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        self.status_code = status_code

        super().__init__(message)


class AuthenticationError(ControlPlaneError):
    """Credential rejected. Never retried with the same credential."""
