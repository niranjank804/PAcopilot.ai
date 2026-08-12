"""Control plane — the human-facing half of report automation.

Route shape follows the existing convention in this codebase: a single
router with one prefix, `ApiResponse` envelopes, `require_permission`
guards, and `audit_service.log()` on every state-changing action. Nested
resources use distinct literal segments (`/reports/definitions/{id}`,
`/reports/workers/{id}`) rather than sharing the `/reports/{id}` space,
so no route depends on declaration order to avoid being shadowed.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.api.dependencies.rate_limit import general_rate_limited
from src.database.session import get_db
from src.reports.artifact_service import artifact_service
from src.reports.audit_actions import ReportAuditAction
from src.reports.enums import ReportStatus
from src.reports.execution_service import execution_service
from src.reports.report_service import report_service
from src.reports.workbook_service import workbook_service
from src.reports.worker_service import worker_service
from src.schemas.auth import UserResponse
from src.schemas.reports import (
    ArtifactResponse,
    ExecutionDetailResponse,
    ExecutionResponse,
    ReportCreate,
    ReportResponse,
    ReportStatusUpdate,
    ReportUpdate,
    RunNowResponse,
    WorkbookResponse,
    WorkerCredentialResponse,
    WorkerEnrollmentResponse,
    WorkerRegisterRequest,
    WorkerResponse,
)
from src.schemas.response import ApiResponse
from src.services.audit_service import audit_service

router = APIRouter(
    prefix="/reports",
    tags=["Report Automation"],
)

_ENROLLMENT_INSTRUCTIONS = (
    "Run `pa-worker enroll --server <PA-Copilot URL> --token <token>` on the "
    "Windows machine. This token is shown once, is single-use, and expires."
)


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


def _worker_response(worker) -> WorkerResponse:
    """Build the response with a *derived* status.

    The stored status is what the worker last claimed. A worker that
    crashed never got to write OFFLINE, so the console must show status
    computed against the heartbeat clock instead.
    """

    return WorkerResponse(
        id=worker.id,
        name=worker.name,
        description=worker.description,
        status=worker_service.effective_status(worker),
        version=worker.version,
        os=worker.os,
        excel_version=worker.excel_version,
        pafe_version=worker.pafe_version,
        hostname=worker.hostname,
        capabilities=list(worker.capabilities or []),
        last_heartbeat_at=worker.last_heartbeat_at,
        enrolled_at=worker.enrolled_at,
        disabled_at=worker.disabled_at,
        last_error=worker.last_error,
        created_at=worker.created_at,
    )


# ======================================================================
# Workbooks
# ======================================================================


@router.post(
    "/workbooks",
    response_model=ApiResponse[WorkbookResponse],
    status_code=201,
)
async def upload_workbook(
    http_request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.create")),
    _: UserResponse = Depends(general_rate_limited),
):
    file_bytes = await file.read()

    workbook = await workbook_service.upload(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        name=name,
        # The raw client filename. Sanitized inside the service — it is
        # never used as a path here or on the worker.
        filename=file.filename or "workbook.xlsx",
        file_bytes=file_bytes,
        description=description,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKBOOK_UPLOADED.value,
        entity="report_workbook",
        entity_id=workbook.id,
        new_values={
            "name": workbook.name,
            "filename": workbook.filename,
            "checksum": workbook.checksum,
            "size_bytes": workbook.size_bytes,
            "version": workbook.version,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True, data=WorkbookResponse.model_validate(workbook)
    )


@router.get(
    "/workbooks",
    response_model=ApiResponse[list[WorkbookResponse]],
)
async def list_workbooks(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    workbooks = await workbook_service.list_workbooks(
        db, current_user.organization_id
    )

    return ApiResponse(
        success=True,
        data=[WorkbookResponse.model_validate(item) for item in workbooks],
    )


@router.delete(
    "/workbooks/{workbook_id}",
    response_model=ApiResponse[None],
)
async def delete_workbook(
    workbook_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.manage")),
):
    await workbook_service.delete(
        db, workbook_id, current_user.organization_id
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKBOOK_DELETED.value,
        entity="report_workbook",
        entity_id=workbook_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=None)


# ======================================================================
# Workers
# ======================================================================


@router.post(
    "/workers",
    response_model=ApiResponse[WorkerEnrollmentResponse],
    status_code=201,
)
async def register_worker(
    payload: WorkerRegisterRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.manage")),
):
    """Create a worker slot and mint its single-use enrollment token.

    The token is in this response and in no other: it is stored only as a
    keyed digest. It is deliberately not written to the audit log either
    — the audit record proves a worker was registered, without becoming a
    second place the secret lives.
    """

    worker, token = await worker_service.register(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKER_REGISTERED.value,
        entity="report_worker",
        entity_id=worker.id,
        new_values={"name": worker.name},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True,
        data=WorkerEnrollmentResponse(
            worker=_worker_response(worker),
            enrollment_token=token,
            expires_at=worker.enrollment_expires_at,
            instructions=_ENROLLMENT_INSTRUCTIONS,
        ),
    )


@router.get(
    "/workers",
    response_model=ApiResponse[list[WorkerResponse]],
)
async def list_workers(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.read")),
):
    workers = await worker_service.list_workers(
        db, current_user.organization_id
    )

    return ApiResponse(
        success=True, data=[_worker_response(worker) for worker in workers]
    )


@router.get(
    "/workers/{worker_id}",
    response_model=ApiResponse[WorkerResponse],
)
async def get_worker(
    worker_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.read")),
):
    worker = await worker_service.get_worker(
        db, worker_id, current_user.organization_id
    )

    return ApiResponse(success=True, data=_worker_response(worker))


@router.post(
    "/workers/{worker_id}/enrollment",
    response_model=ApiResponse[WorkerEnrollmentResponse],
)
async def reissue_enrollment(
    worker_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.manage")),
):
    """Mint a fresh enrollment token, invalidating the old credential."""

    worker, token = await worker_service.reissue_enrollment(
        db, worker_id, current_user.organization_id
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKER_ENROLLMENT_REISSUED.value,
        entity="report_worker",
        entity_id=worker.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True,
        data=WorkerEnrollmentResponse(
            worker=_worker_response(worker),
            enrollment_token=token,
            expires_at=worker.enrollment_expires_at,
            instructions=_ENROLLMENT_INSTRUCTIONS,
        ),
    )


@router.post(
    "/workers/{worker_id}/rotate",
    response_model=ApiResponse[WorkerCredentialResponse],
)
async def rotate_worker_credential(
    worker_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.manage")),
):
    """Issue a new credential; every token already in flight stops working."""

    worker, secret = await worker_service.rotate_credential(
        db, worker_id, current_user.organization_id
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKER_CREDENTIAL_ROTATED.value,
        entity="report_worker",
        entity_id=worker.id,
        new_values={"secret_version": worker.secret_version},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True,
        data=WorkerCredentialResponse(
            worker_id=worker.id,
            worker_secret=secret,
            secret_version=worker.secret_version,
        ),
    )


@router.post(
    "/workers/{worker_id}/disable",
    response_model=ApiResponse[WorkerResponse],
)
async def disable_worker(
    worker_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.manage")),
):
    worker = await worker_service.set_enabled(
        db, worker_id, current_user.organization_id, enabled=False
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKER_DISABLED.value,
        entity="report_worker",
        entity_id=worker.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=_worker_response(worker))


@router.post(
    "/workers/{worker_id}/enable",
    response_model=ApiResponse[WorkerResponse],
)
async def enable_worker(
    worker_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("workers.manage")),
):
    worker = await worker_service.set_enabled(
        db, worker_id, current_user.organization_id, enabled=True
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.WORKER_ENABLED.value,
        entity="report_worker",
        entity_id=worker.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=_worker_response(worker))


# ======================================================================
# Report definitions
# ======================================================================


@router.post(
    "/definitions",
    response_model=ApiResponse[ReportResponse],
    status_code=201,
)
async def create_report(
    payload: ReportCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.create")),
    _: UserResponse = Depends(general_rate_limited),
):
    report = await report_service.create(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        report_type=payload.report_type,
        workbook_id=payload.workbook_id,
        connection_id=payload.connection_id,
        worker_id=payload.worker_id,
        output_formats=payload.output_formats,
        parameters=payload.parameters,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.REPORT_CREATED.value,
        entity="report_definition",
        entity_id=report.id,
        new_values={
            "name": report.name,
            "report_type": report.report_type,
            "workbook_id": str(report.workbook_id),
            "output_formats": report.output_formats,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=ReportResponse.model_validate(report))


@router.get(
    "/definitions",
    response_model=ApiResponse[list[ReportResponse]],
)
async def list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    reports = await report_service.list_reports(
        db, current_user.organization_id
    )

    return ApiResponse(
        success=True,
        data=[ReportResponse.model_validate(item) for item in reports],
    )


@router.get(
    "/definitions/{report_id}",
    response_model=ApiResponse[ReportResponse],
)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    report = await report_service.get_report(
        db, report_id, current_user.organization_id
    )

    return ApiResponse(success=True, data=ReportResponse.model_validate(report))


@router.patch(
    "/definitions/{report_id}",
    response_model=ApiResponse[ReportResponse],
)
async def update_report(
    report_id: uuid.UUID,
    payload: ReportUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.update")),
):
    report = await report_service.update(
        db,
        report_id,
        current_user.organization_id,
        name=payload.name,
        description=payload.description,
        workbook_id=payload.workbook_id,
        connection_id=payload.connection_id,
        worker_id=payload.worker_id,
        output_formats=payload.output_formats,
        parameters=payload.parameters,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.REPORT_UPDATED.value,
        entity="report_definition",
        entity_id=report.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=ReportResponse.model_validate(report))


@router.post(
    "/definitions/{report_id}/status",
    response_model=ApiResponse[ReportResponse],
)
async def set_report_status(
    report_id: uuid.UUID,
    payload: ReportStatusUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.update")),
):
    """Pause / resume / archive. Reports are never hard-deleted — their
    execution history references them with ON DELETE RESTRICT."""

    report = await report_service.set_status(
        db, report_id, current_user.organization_id, status=payload.status
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=(
            ReportAuditAction.REPORT_ARCHIVED.value
            if payload.status == ReportStatus.ARCHIVED
            else ReportAuditAction.REPORT_UPDATED.value
        ),
        entity="report_definition",
        entity_id=report.id,
        new_values={"status": report.status},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=ReportResponse.model_validate(report))


@router.post(
    "/definitions/{report_id}/run",
    response_model=ApiResponse[RunNowResponse],
    status_code=201,
)
async def run_now(
    report_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.execute")),
    _: UserResponse = Depends(general_rate_limited),
):
    """The only way a report starts today.

    `reports.execute` is the governance boundary for this phase: a user
    who cannot execute cannot cause a workbook to run, and nothing else
    in the system enqueues work. Scheduling (Phase 3) is where automatic
    triggering arrives, and STET approval (Phase 6) is what will gate it.
    """

    execution, created = await report_service.run_now(
        db,
        report_id,
        current_user.organization_id,
        user_id=current_user.id,
    )

    if created:
        ip_address, user_agent = _client_context(http_request)

        await audit_service.log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=ReportAuditAction.EXECUTION_CREATED.value,
            entity="report_execution",
            entity_id=execution.id,
            new_values={
                "report_id": str(report_id),
                "trigger_type": execution.trigger_type,
                "correlation_id": str(execution.correlation_id),
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )

    return ApiResponse(
        success=True,
        data=RunNowResponse(
            execution=ExecutionResponse.model_validate(execution),
            created=created,
        ),
    )


@router.get(
    "/definitions/{report_id}/executions",
    response_model=ApiResponse[list[ExecutionResponse]],
)
async def list_report_executions(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    # Resolves-or-404s inside this organization before the list query, so
    # a foreign report id cannot be used to probe for existence.
    await report_service.get_report(
        db, report_id, current_user.organization_id
    )

    executions = await execution_service.list_executions(
        db,
        current_user.organization_id,
        report_id=report_id,
        limit=limit,
        offset=offset,
    )

    return ApiResponse(
        success=True,
        data=[ExecutionResponse.model_validate(item) for item in executions],
    )


# ======================================================================
# Executions
# ======================================================================


@router.get(
    "/executions",
    response_model=ApiResponse[list[ExecutionResponse]],
)
async def list_executions(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    executions = await execution_service.list_executions(
        db,
        current_user.organization_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return ApiResponse(
        success=True,
        data=[ExecutionResponse.model_validate(item) for item in executions],
    )


@router.get(
    "/executions/{execution_id}",
    response_model=ApiResponse[ExecutionDetailResponse],
)
async def get_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    execution = await execution_service.get_execution(
        db, execution_id, current_user.organization_id
    )

    artifacts = await artifact_service.list_for_execution(db, execution)

    detail = ExecutionDetailResponse.model_validate(execution)
    detail.artifacts = [
        ArtifactResponse.model_validate(item) for item in artifacts
    ]

    return ApiResponse(success=True, data=detail)


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=ApiResponse[ExecutionResponse],
)
async def cancel_execution(
    execution_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.execute")),
):
    """Mark an execution cancelled.

    This is a control-plane decision only. A worker already inside a
    refresh is not interrupted mid-COM-call — it discovers the
    cancellation when its next progress call is rejected, and cleans up.
    """

    execution = await execution_service.get_execution(
        db, execution_id, current_user.organization_id
    )

    execution = await execution_service.cancel(db, execution)

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=ReportAuditAction.EXECUTION_CANCELLED.value,
        entity="report_execution",
        entity_id=execution.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(
        success=True, data=ExecutionResponse.model_validate(execution)
    )


@router.get(
    "/executions/{execution_id}/artifacts",
    response_model=ApiResponse[list[ArtifactResponse]],
)
async def list_execution_artifacts(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    execution = await execution_service.get_execution(
        db, execution_id, current_user.organization_id
    )

    artifacts = await artifact_service.list_for_execution(db, execution)

    return ApiResponse(
        success=True,
        data=[ArtifactResponse.model_validate(item) for item in artifacts],
    )


# ======================================================================
# Artifacts
# ======================================================================


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("reports.read")),
):
    """Stream an artifact back to an authorized user.

    Authorization is re-evaluated on every request: permission, then
    organization ownership. There is no signed URL and no path in the
    response, so an artifact id that leaks is not a capability — the
    holder still needs a valid session in the owning organization.
    """

    artifact = await artifact_service.get_artifact(
        db, artifact_id, current_user.organization_id
    )

    data = await artifact_service.get_content(db, artifact)

    return Response(
        content=data,
        media_type=artifact.mime_type,
        headers={
            # The filename is server-generated (see
            # artifact_service._artifact_filename) so it cannot carry a
            # newline or quote into this header.
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
