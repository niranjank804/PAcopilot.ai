"""Worker plane — the endpoints a customer's Windows worker calls.

Every route here is either unauthenticated-by-design (enrollment and
credential exchange, which are how identity is *established*) or
authenticated as a worker, never as a user. Three rules hold across all
of them:

1. **Organization is never taken from the request.** It is read from the
   worker row the credential resolved to. There is no field in any
   request body on this router that names an organization, a report, or a
   workbook the server did not already associate with this worker.

2. **A worker addresses only its own execution.** Every `/jobs/{id}`
   route resolves the execution and then asserts both
   `execution.organization_id == worker.organization_id` and
   `execution.worker_id == worker.id`, answering 404 (not 403) on either
   failure.

3. **No route accepts code.** The job payload carries an allowlisted
   `operation` verb and typed parameters. There is no field that can
   carry VBA, a macro name, a shell command, or a filesystem path.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.worker_auth import get_current_worker
from src.core.config import settings
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.core.logging import app_logger
from src.database.models.report_execution import ReportExecution
from src.database.models.report_worker import ReportWorker
from src.database.session import get_db
from src.repositories.report_execution_repository import (
    report_execution_repository,
)
from src.repositories.tm1_connection_repository import (
    tm1_connection_repository,
)
from src.reports.artifact_service import artifact_service
from src.reports.audit_actions import ReportAuditAction
from src.reports.enums import (
    LEASED_EXECUTION_STATUSES,
    ExecutionStatus,
    OutputFormat,
)
from src.reports.errors import coerce_error_code
from src.reports.execution_service import execution_service
from src.reports.operations import operation_for_report
from src.reports.workbook_service import workbook_service
from src.reports.worker_credentials import create_worker_token
from src.reports.worker_service import worker_service
from src.schemas.reports import (
    WorkerCompleteRequest,
    WorkerEnrollRequest,
    WorkerEnrollResponse,
    WorkerFailRequest,
    WorkerFailResponse,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerJobConnection,
    WorkerJobResponse,
    WorkerJobWorkbook,
    WorkerProgressRequest,
    WorkerTokenRequest,
    WorkerTokenResponse,
)
from src.schemas.response import ApiResponse
from src.services.audit_service import audit_service

router = APIRouter(
    prefix="/worker",
    tags=["Report Automation — Worker"],
)


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


async def _owned_execution(
    db: AsyncSession,
    execution_id: uuid.UUID,
    worker: ReportWorker,
) -> ReportExecution:
    """Resolve an execution this worker is actually entitled to touch.

    A single 404 for every failure — wrong organization, wrong worker, or
    genuinely absent. Distinguishing them would let a worker enumerate
    other tenants' execution ids by response code.
    """

    execution = await report_execution_repository.get_by_id(db, execution_id)

    if execution is None:
        raise NotFoundException("Execution not found.")

    if execution.organization_id != worker.organization_id:
        raise NotFoundException("Execution not found.")

    if execution.worker_id != worker.id:
        raise NotFoundException("Execution not found.")

    return execution


# ======================================================================
# Identity — the only unauthenticated routes on this router
# ======================================================================


@router.post(
    "/enroll",
    response_model=ApiResponse[WorkerEnrollResponse],
)
async def enroll(
    payload: WorkerEnrollRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Spend a single-use enrollment token for a long-lived credential.

    Unauthenticated by necessity — the worker has no identity yet. The
    token *is* the organization binding: it was minted against one
    worker row, and that row's organization is what gets used. Nothing
    in the request body influences which organization the worker joins.
    """

    worker, secret = await worker_service.enroll(
        db,
        enrollment_token=payload.enrollment_token,
        host_facts=payload.host.model_dump(),
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=worker.organization_id,
        # No user: the actor is the machine. The registering admin is
        # already recorded on the WORKER_REGISTERED entry.
        user_id=None,
        action=ReportAuditAction.WORKER_ENROLLED.value,
        entity="report_worker",
        entity_id=worker.id,
        new_values={
            "hostname": worker.hostname,
            "os": worker.os,
            "excel_version": worker.excel_version,
            "pafe_version": worker.pafe_version,
            "capabilities": worker.capabilities,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True,
        data=WorkerEnrollResponse(
            worker_id=worker.id,
            worker_secret=secret,
            organization_id=worker.organization_id,
            secret_version=worker.secret_version,
        ),
    )


@router.post(
    "/token",
    response_model=ApiResponse[WorkerTokenResponse],
)
async def issue_token(
    payload: WorkerTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange the long-lived credential for a short-lived access token.

    This is the only route that accepts the credential itself, which is
    what keeps it off every other request. The returned token expires in
    minutes and carries the credential's version, so a rotation
    invalidates it immediately.
    """

    worker = await worker_service.authenticate(
        db,
        worker_id=payload.worker_id,
        secret=payload.worker_secret,
    )

    token, expires_in = create_worker_token(
        worker_id=worker.id,
        organization_id=worker.organization_id,
        secret_version=worker.secret_version,
    )

    return ApiResponse(
        success=True,
        data=WorkerTokenResponse(access_token=token, expires_in=expires_in),
    )


# ======================================================================
# Liveness
# ======================================================================


@router.post(
    "/heartbeat",
    response_model=ApiResponse[WorkerHeartbeatResponse],
)
async def heartbeat(
    payload: WorkerHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Liveness plus a re-statement of verified host facts.

    A single late heartbeat does not make a worker OFFLINE — the console
    derives that from `REPORT_WORKER_OFFLINE_AFTER_SECONDS` (three missed
    beats by default), so a network blip does not flip the status.
    """

    worker = await worker_service.heartbeat(
        db,
        worker,
        host_facts=payload.host.model_dump() if payload.host else None,
        busy=payload.busy,
        last_error=payload.last_error,
    )

    active = await report_execution_repository.list_by_organization(
        db, worker.organization_id, limit=200
    )

    active_ids = [
        execution.id
        for execution in active
        if execution.worker_id == worker.id
        and ExecutionStatus(execution.status) in LEASED_EXECUTION_STATUSES
    ]

    return ApiResponse(
        success=True,
        data=WorkerHeartbeatResponse(
            status=worker_service.effective_status(worker),
            heartbeat_interval_seconds=settings.REPORT_WORKER_HEARTBEAT_SECONDS,
            active_execution_ids=active_ids,
        ),
    )


# ======================================================================
# Jobs
# ======================================================================


@router.post(
    "/jobs/claim",
    response_model=ApiResponse[WorkerJobResponse | None],
)
async def claim_job(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Atomically take at most one execution, or return null.

    The claim itself is a single `UPDATE ... WHERE id = (SELECT ... FOR
    UPDATE SKIP LOCKED LIMIT 1) RETURNING id` — never a SELECT followed
    by a separate UPDATE. Two workers polling simultaneously therefore
    take different rows, and the same execution can never be handed out
    twice.
    """

    execution = await execution_service.claim_next(db, worker)

    if execution is None:
        return ApiResponse(success=True, data=None)

    report = await execution_service.get_report_for_execution(db, execution)

    # Re-resolved from the execution, not from anything the worker sent.
    workbook = await workbook_service.get_workbook(
        db,
        execution.workbook_id,
        worker.organization_id,
    )

    connection = None

    if report.connection_id is not None:
        row = await tm1_connection_repository.get_by_id(db, report.connection_id)

        # Non-secret coordinates only. `encrypted_password` is on that row
        # and is deliberately not read, not decrypted, and not sent — a
        # job payload never carries a credential.
        if row is not None and row.organization_id == worker.organization_id:
            connection = WorkerJobConnection(
                id=row.id,
                name=row.name,
                address=row.address,
                port=row.port,
                ssl=row.ssl,
                authentication_type=row.authentication_type,
                tenant=row.tenant,
                database=row.database,
            )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=worker.organization_id,
        user_id=None,
        action=ReportAuditAction.EXECUTION_CLAIMED.value,
        entity="report_execution",
        entity_id=execution.id,
        new_values={
            "worker_id": str(worker.id),
            "attempt": execution.attempt,
            "correlation_id": str(execution.correlation_id),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    app_logger.info(
        "report_automation job claimed "
        f"correlation_id={execution.correlation_id} "
        f"execution_id={execution.id} organization_id={worker.organization_id} "
        f"report_id={report.id} worker_id={worker.id} "
        f"attempt={execution.attempt}"
    )

    return ApiResponse(
        success=True,
        data=WorkerJobResponse(
            execution_id=execution.id,
            report_id=report.id,
            correlation_id=execution.correlation_id,
            # An allowlisted verb chosen by the server from the report's
            # type. The worker rejects anything it does not implement.
            operation=operation_for_report(report).value,
            output_formats=[
                OutputFormat(value) for value in report.output_formats
            ],
            workbook=WorkerJobWorkbook(
                id=workbook.id,
                filename=workbook.filename,
                checksum=workbook.checksum,
                size_bytes=workbook.size_bytes,
                content_type=workbook.content_type,
            ),
            connection=connection,
            timeout_seconds=execution.timeout_seconds,
            lease_seconds=settings.REPORT_EXECUTION_LEASE_SECONDS,
            attempt=execution.attempt,
        ),
    )


@router.get("/jobs/{execution_id}/workbook")
async def download_job_workbook(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Serve the workbook bytes for an execution this worker holds.

    Addressed by *execution*, not by workbook id. A worker therefore
    cannot enumerate its organization's workbook library — it can only
    fetch the one file attached to the job it was actually given.
    """

    execution = await _owned_execution(db, execution_id, worker)

    workbook = await workbook_service.get_workbook(
        db, execution.workbook_id, worker.organization_id
    )

    data = await workbook_service.get_content(db, workbook)

    return Response(
        content=data,
        media_type=workbook.content_type,
        headers={
            "X-Workbook-Checksum": workbook.checksum,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/jobs/{execution_id}/start",
    response_model=ApiResponse[dict],
)
async def start_job(
    execution_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    execution = await _owned_execution(db, execution_id, worker)

    execution = await execution_service.mark_started(db, execution, worker)

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=worker.organization_id,
        user_id=None,
        action=ReportAuditAction.EXECUTION_STARTED.value,
        entity="report_execution",
        entity_id=execution.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True,
        data={
            "status": execution.status,
            "lease_seconds": settings.REPORT_EXECUTION_LEASE_SECONDS,
        },
    )


@router.post(
    "/jobs/{execution_id}/progress",
    response_model=ApiResponse[dict],
)
async def report_progress(
    execution_id: uuid.UUID,
    payload: WorkerProgressRequest,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Extend the lease and record which step the worker reached.

    Also where the execution's own timeout is enforced: if the run has
    exceeded its allowance the server fails it here rather than letting a
    worker heartbeat around a wedged Excel indefinitely.
    """

    execution = await _owned_execution(db, execution_id, worker)

    execution = await execution_service.extend_lease(
        db, execution, worker, step=payload.step
    )

    return ApiResponse(
        success=True,
        data={
            "status": execution.status,
            "lease_seconds": settings.REPORT_EXECUTION_LEASE_SECONDS,
        },
    )


@router.post(
    "/jobs/{execution_id}/artifacts",
    response_model=ApiResponse[dict],
    status_code=201,
)
async def upload_artifact(
    execution_id: uuid.UUID,
    http_request: Request,
    file: UploadFile = File(...),
    output_format: str = Form(...),
    checksum: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Store one generated artifact.

    Idempotent per (execution, format): a worker whose upload succeeded
    but whose response was lost retries and receives its existing
    artifact, rather than creating a duplicate. Re-uploading *different*
    bytes into the same slot is a conflict, not a retry.
    """

    execution = await _owned_execution(db, execution_id, worker)

    if ExecutionStatus(execution.status) not in LEASED_EXECUTION_STATUSES:
        # Uploading into a finished execution would let a late worker
        # attach output to a run already reported as failed or cancelled.
        raise ConflictException(
            "This execution is no longer accepting artifacts.",
            code="INVALID_EXECUTION_TRANSITION",
        )

    try:
        parsed_format = OutputFormat(output_format)
    except ValueError:
        raise ValidationException(f"Unknown output format: {output_format}")

    data = await file.read()

    artifact, created = await artifact_service.record_upload(
        db,
        execution=execution,
        output_format=parsed_format,
        filename=file.filename or "report",
        data=data,
        declared_checksum=checksum,
    )

    if created:
        ip_address, user_agent = _client_context(http_request)

        await audit_service.log(
            db,
            organization_id=worker.organization_id,
            user_id=None,
            action=ReportAuditAction.ARTIFACT_CREATED.value,
            entity="report_artifact",
            entity_id=artifact.id,
            new_values={
                "execution_id": str(execution.id),
                "output_format": artifact.output_format,
                "size_bytes": artifact.size_bytes,
                "checksum": artifact.checksum,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

    return ApiResponse(
        success=True,
        data={
            "artifact_id": str(artifact.id),
            "created": created,
            "checksum": artifact.checksum,
        },
    )


@router.post(
    "/jobs/{execution_id}/complete",
    response_model=ApiResponse[dict],
)
async def complete_job(
    execution_id: uuid.UUID,
    payload: WorkerCompleteRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Report success.

    Idempotent by design: a worker that succeeded but lost the response
    retries, and an already-SUCCEEDED execution returns success rather
    than a state-machine conflict. Without this, "Excel finished, then
    the network dropped" would turn a good run into a failure and a
    duplicate re-run.
    """

    execution = await _owned_execution(db, execution_id, worker)

    if ExecutionStatus(execution.status) == ExecutionStatus.SUCCEEDED:
        return ApiResponse(
            success=True,
            data={"status": execution.status, "already_recorded": True},
        )

    execution = await execution_service.succeed(
        db,
        execution,
        worker,
        trace_log=payload.trace_log,
        diagnostics=payload.diagnostics,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=worker.organization_id,
        user_id=None,
        action=ReportAuditAction.EXECUTION_SUCCEEDED.value,
        entity="report_execution",
        entity_id=execution.id,
        new_values={
            "duration_ms": execution.duration_ms,
            "attempt": execution.attempt,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    app_logger.info(
        "report_automation job succeeded "
        f"correlation_id={execution.correlation_id} "
        f"execution_id={execution.id} organization_id={worker.organization_id} "
        f"worker_id={worker.id} duration_ms={execution.duration_ms}"
    )

    return ApiResponse(
        success=True,
        data={"status": execution.status, "already_recorded": False},
    )


@router.post(
    "/jobs/{execution_id}/fail",
    response_model=ApiResponse[WorkerFailResponse],
)
async def fail_job(
    execution_id: uuid.UUID,
    payload: WorkerFailRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    worker: ReportWorker = Depends(get_current_worker),
):
    """Report failure, and let the server decide about a retry.

    The worker sends a code, not a verdict. Whether that code is
    retryable is decided by `retry_class_for()` on this side, so a
    compromised or buggy worker cannot talk the control plane into
    retrying forever — and the attempt cap applies regardless.
    """

    execution = await _owned_execution(db, execution_id, worker)

    error_code = coerce_error_code(payload.error_code)

    execution = await execution_service.fail(
        db,
        execution,
        worker=worker,
        error_code=error_code,
        trace_log=payload.trace_log,
        diagnostics=payload.diagnostics,
    )

    retry = await execution_service.create_retry(db, execution)

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=worker.organization_id,
        user_id=None,
        action=ReportAuditAction.EXECUTION_FAILED.value,
        entity="report_execution",
        entity_id=execution.id,
        new_values={
            "error_code": execution.error_code,
            "retry_class": execution.retry_class,
            "attempt": execution.attempt,
            "retry_execution_id": str(retry.id) if retry else None,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if retry is not None:
        await audit_service.log(
            db,
            organization_id=worker.organization_id,
            user_id=None,
            action=ReportAuditAction.EXECUTION_RETRY_SCHEDULED.value,
            entity="report_execution",
            entity_id=retry.id,
            new_values={
                "parent_execution_id": str(execution.id),
                "attempt": retry.attempt,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

    app_logger.info(
        "report_automation job failed "
        f"correlation_id={execution.correlation_id} "
        f"execution_id={execution.id} organization_id={worker.organization_id} "
        f"worker_id={worker.id} error_code={execution.error_code} "
        f"retry_class={execution.retry_class} "
        f"retry_execution_id={retry.id if retry else None}"
    )

    return ApiResponse(
        success=True,
        data=WorkerFailResponse(
            # `execution` is the row the worker just failed; if a retry
            # was created this row is now RETRYING.
            status=ExecutionStatus(execution.status),
            retry_class=execution.retry_class,
            retry_execution_id=retry.id if retry else None,
        ),
    )
