"""Request/response shapes for report automation.

Response models are explicit about what they *omit*: no
`storage_reference`, no `secret_hash`, no `enrollment_token_hash`. Those
columns exist on the ORM rows these are built from, so leaving them out
is the mechanism that keeps them server-side — `from_attributes` copies
only the fields declared here.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.reports.enums import (
    ExecutionStatus,
    OutputFormat,
    ReportStatus,
    WorkerCapability,
    WorkerStatus,
)

# ----------------------------------------------------------------------
# Workbooks
# ----------------------------------------------------------------------


class WorkbookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    filename: str
    content_type: str
    checksum: str
    size_bytes: int
    version: int
    status: str
    description: str | None = None
    created_at: datetime


# ----------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------


class ReportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    # Free string rather than the enum: the service maps it through
    # validate_report_type(), which distinguishes "unknown type" from
    # "reserved for a future release" — a distinction a 422 from pydantic
    # would flatten into "not a valid enumeration member".
    report_type: str = "pafe_workbook"
    workbook_id: uuid.UUID
    connection_id: uuid.UUID | None = None
    worker_id: uuid.UUID | None = None
    output_formats: list[str] = Field(default_factory=lambda: ["xlsx"])
    parameters: dict | None = None


class ReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    workbook_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    worker_id: uuid.UUID | None = None
    output_formats: list[str] | None = None
    parameters: dict | None = None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    report_type: str
    workbook_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    worker_id: uuid.UUID | None = None
    output_formats: list[str]
    parameters: dict | None = None
    status: str
    approval_status: str
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------
# Workers
# ----------------------------------------------------------------------


class WorkerRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    # Derived from the heartbeat clock, not copied from the row — see
    # worker_service.effective_status().
    status: WorkerStatus
    version: str | None = None
    os: str | None = None
    excel_version: str | None = None
    pafe_version: str | None = None
    hostname: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    last_heartbeat_at: datetime | None = None
    enrolled_at: datetime | None = None
    disabled_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime


class WorkerEnrollmentResponse(BaseModel):
    """The one and only time the enrollment token is readable."""

    worker: WorkerResponse
    enrollment_token: str
    expires_at: datetime | None = None
    instructions: str


class WorkerCredentialResponse(BaseModel):
    """The one and only time a rotated credential is readable."""

    worker_id: uuid.UUID
    worker_secret: str
    secret_version: int


# ----------------------------------------------------------------------
# Executions
# ----------------------------------------------------------------------


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_execution_id: uuid.UUID
    output_format: str
    filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    created_at: datetime


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    workbook_id: uuid.UUID | None = None
    worker_id: uuid.UUID | None = None
    status: ExecutionStatus
    trigger_type: str
    correlation_id: uuid.UUID
    attempt: int
    max_attempts: int
    parent_execution_id: uuid.UUID | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    timeout_seconds: int
    error_code: str | None = None
    error_message: str | None = None
    retry_class: str | None = None
    diagnostics: dict | None = None
    created_at: datetime


class ExecutionDetailResponse(ExecutionResponse):
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    # IBM PAfE automation TraceLog. Only on the detail view, which needs
    # reports.read plus organization ownership.
    trace_log: str | None = None


class RunNowResponse(BaseModel):
    execution: ExecutionResponse
    # False when an identical request in the same minute already produced
    # this execution. The caller should treat that as success.
    created: bool


# ----------------------------------------------------------------------
# Worker plane — what the worker process itself sends and receives
# ----------------------------------------------------------------------


class WorkerHostFacts(BaseModel):
    """Self-reported host facts.

    Capabilities are a claim the worker's own probe made, and are
    intersected with the known set server-side before being stored.
    """

    version: str | None = Field(default=None, max_length=30)
    os: str | None = Field(default=None, max_length=100)
    excel_version: str | None = Field(default=None, max_length=50)
    pafe_version: str | None = Field(default=None, max_length=50)
    hostname: str | None = Field(default=None, max_length=100)
    capabilities: list[WorkerCapability] = Field(default_factory=list)


class WorkerEnrollRequest(BaseModel):
    enrollment_token: str = Field(min_length=8, max_length=200)
    host: WorkerHostFacts = Field(default_factory=WorkerHostFacts)


class WorkerEnrollResponse(BaseModel):
    worker_id: uuid.UUID
    worker_secret: str
    organization_id: uuid.UUID
    secret_version: int


class WorkerTokenRequest(BaseModel):
    worker_id: uuid.UUID
    worker_secret: str = Field(min_length=8, max_length=200)


class WorkerTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class WorkerHeartbeatRequest(BaseModel):
    busy: bool = False
    host: WorkerHostFacts | None = None
    last_error: str | None = Field(default=None, max_length=500)


class WorkerHeartbeatResponse(BaseModel):
    status: WorkerStatus
    heartbeat_interval_seconds: int
    # Executions the server believes this worker still holds. A worker
    # that restarted uses this to notice it has orphaned work rather than
    # silently leaving it to the reaper.
    active_execution_ids: list[uuid.UUID] = Field(default_factory=list)


class WorkerJobWorkbook(BaseModel):
    id: uuid.UUID
    filename: str
    checksum: str
    size_bytes: int
    content_type: str


class WorkerJobConnection(BaseModel):
    """Non-secret TM1 coordinates only.

    There is deliberately no password field. Credentials are never put
    into a job payload; where PAfE `Logon` is usable at all, the worker
    supplies credentials from its own local secure store. See
    docs/report-automation/README.md for the supported auth scenarios.
    """

    id: uuid.UUID
    name: str
    address: str
    port: int
    ssl: bool
    authentication_type: str
    tenant: str | None = None
    database: str | None = None


class WorkerJobResponse(BaseModel):
    """The allowlisted command a worker is permitted to run.

    `operation` is an enum-constrained verb, not a script. There is no
    field anywhere in this payload that can carry VBA, a shell command,
    a file path, or a macro name — that is the hard boundary described in
    docs/report-automation/README.md.
    """

    execution_id: uuid.UUID
    report_id: uuid.UUID
    correlation_id: uuid.UUID
    operation: str
    output_formats: list[OutputFormat]
    workbook: WorkerJobWorkbook
    connection: WorkerJobConnection | None = None
    timeout_seconds: int
    lease_seconds: int
    attempt: int


class WorkerProgressRequest(BaseModel):
    step: str | None = Field(default=None, max_length=100)


class WorkerCompleteRequest(BaseModel):
    trace_log: str | None = None
    diagnostics: dict | None = None


class WorkerFailRequest(BaseModel):
    # Coerced through coerce_error_code() server-side: an unrecognised
    # value becomes INTERNAL_ERROR rather than being stored verbatim.
    error_code: str = Field(max_length=50)
    diagnostics: dict | None = None
    trace_log: str | None = None


class WorkerFailResponse(BaseModel):
    status: ExecutionStatus
    retry_class: str | None = None
    retry_execution_id: uuid.UUID | None = None


class ReportStatusUpdate(BaseModel):
    status: ReportStatus
