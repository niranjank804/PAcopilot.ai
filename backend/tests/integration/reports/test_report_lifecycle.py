"""The POC lifecycle, driven entirely through the HTTP API."""

import pytest
from sqlalchemy import select

from src.database.models.audit_log import AuditLog
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.reports.helpers import (
    claim,
    create_report,
    run_now,
    setup_runnable_report,
    upload_workbook,
    worker_headers,
)


@pytest.mark.asyncio
async def test_full_poc_lifecycle(client, db_session):
    """Register → enroll → upload → create → run → claim → run → succeed.

    This is the acceptance path from the spec, minus the Excel work
    itself (which happens on the worker and is covered by the worker's
    own tests).
    """

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    # --- Admin registers a worker; it enrolls and comes online ---
    worker_auth, worker_id = await worker_headers(client, headers)

    listed = await client.get("/reports/workers", headers=headers)
    worker = listed.json()["data"][0]

    assert worker["status"] == "online"
    assert worker["excel_version"] == "16.0"
    assert "pafe_automation" in worker["capabilities"]

    # --- Admin uploads a workbook and creates a report ---
    workbook = await upload_workbook(client, headers)

    assert workbook["checksum"]
    # The internal storage locator must never be serialized.
    assert "storage_reference" not in workbook

    report = await create_report(client, headers, workbook["id"])

    # --- Run now: an execution is queued ---
    result = await run_now(client, headers, report["id"])
    execution = result["execution"]

    assert result["created"] is True
    assert execution["status"] == "queued"
    assert execution["attempt"] == 1

    # --- Worker claims it ---
    job = await claim(client, worker_auth)

    assert job is not None
    assert job["execution_id"] == execution["id"]
    assert job["operation"] == "REFRESH_WORKBOOK"
    assert job["workbook"]["checksum"] == workbook["checksum"]
    assert job["output_formats"] == ["xlsx"]
    # No credential anywhere in the job payload.
    assert "password" not in str(job).lower()

    # --- Worker downloads the workbook and verifies it ---
    download = await client.get(
        f"/worker/jobs/{execution['id']}/workbook", headers=worker_auth
    )

    assert download.status_code == 200
    assert download.headers["X-Workbook-Checksum"] == workbook["checksum"]

    # --- Worker starts, uploads an artifact, completes ---
    started = await client.post(
        f"/worker/jobs/{execution['id']}/start", headers=worker_auth
    )

    assert started.json()["data"]["status"] == "running"

    progress = await client.post(
        f"/worker/jobs/{execution['id']}/progress",
        json={"step": "refresh_started"},
        headers=worker_auth,
    )

    assert progress.status_code == 200

    artifact_bytes = b"PK\x03\x04refreshed-output"

    upload = await client.post(
        f"/worker/jobs/{execution['id']}/artifacts",
        files={"file": ("out.xlsx", artifact_bytes, "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_auth,
    )

    assert upload.status_code == 201
    assert upload.json()["data"]["created"] is True

    completed = await client.post(
        f"/worker/jobs/{execution['id']}/complete",
        json={"trace_log": "PAfE automation log: refresh completed"},
        headers=worker_auth,
    )

    assert completed.status_code == 200

    # --- Execution is SUCCEEDED with its artifact attached ---
    detail = await client.get(
        f"/reports/executions/{execution['id']}", headers=headers
    )
    body = detail.json()["data"]

    assert body["status"] == "succeeded"
    assert body["duration_ms"] is not None
    assert len(body["artifacts"]) == 1
    assert body["artifacts"][0]["output_format"] == "xlsx"
    assert body["trace_log"].startswith("PAfE automation log")

    # --- The user can download the artifact ---
    artifact_id = body["artifacts"][0]["id"]

    downloaded = await client.get(
        f"/reports/artifacts/{artifact_id}/download", headers=headers
    )

    assert downloaded.status_code == 200
    assert downloaded.content == artifact_bytes
    assert "attachment" in downloaded.headers["content-disposition"]

    # --- The whole lifecycle is in the audit trail ---
    rows = await db_session.execute(
        select(AuditLog.action).where(
            AuditLog.organization_id == user.organization_id
        )
    )
    actions = set(rows.scalars().all())

    for expected in (
        "REPORT_WORKER_REGISTERED",
        "REPORT_WORKER_ENROLLED",
        "REPORT_WORKBOOK_UPLOADED",
        "REPORT_CREATED",
        "REPORT_EXECUTION_CREATED",
        "REPORT_EXECUTION_CLAIMED",
        "REPORT_EXECUTION_STARTED",
        "REPORT_ARTIFACT_CREATED",
        "REPORT_EXECUTION_SUCCEEDED",
    ):
        assert expected in actions, f"missing audit action: {expected}"


@pytest.mark.asyncio
async def test_failure_is_recorded_and_retried(client, db_session):
    """A retryable failure produces a new attempt, not a reopened row."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    failed = await client.post(
        f"/worker/jobs/{execution['id']}/fail",
        json={"error_code": "tm1_connection_failed"},
        headers=worker_auth,
    )

    data = failed.json()["data"]

    assert data["retry_class"] == "retryable"
    assert data["retry_execution_id"] is not None
    # The failed row moves to RETRYING and stays terminal.
    assert data["status"] == "retrying"

    retry = await client.get(
        f"/reports/executions/{data['retry_execution_id']}", headers=headers
    )
    retry_body = retry.json()["data"]

    assert retry_body["attempt"] == 2
    assert retry_body["parent_execution_id"] == execution["id"]
    assert retry_body["status"] == "queued"
    # Same logical run, so it stays followable across attempts.
    assert retry_body["correlation_id"] == execution["correlation_id"]


@pytest.mark.asyncio
async def test_non_retryable_failure_creates_no_retry(client, db_session):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    failed = await client.post(
        f"/worker/jobs/{execution['id']}/fail",
        json={"error_code": "workbook_checksum_mismatch"},
        headers=worker_auth,
    )

    data = failed.json()["data"]

    assert data["retry_class"] == "non_retryable"
    assert data["retry_execution_id"] is None
    assert data["status"] == "failed"


@pytest.mark.asyncio
async def test_auth_failure_requires_a_human(client, db_session):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    failed = await client.post(
        f"/worker/jobs/{execution['id']}/fail",
        json={"error_code": "tm1_auth_failed"},
        headers=worker_auth,
    )

    data = failed.json()["data"]

    # Retrying cannot fix a rejected credential; a person has to act.
    assert data["retry_class"] == "requires_human"
    assert data["retry_execution_id"] is None


@pytest.mark.asyncio
async def test_cancel_stops_the_worker_at_its_next_progress_call(
    client, db_session
):
    """Cancellation is a control-plane decision the worker discovers."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    cancelled = await client.post(
        f"/reports/executions/{execution['id']}/cancel", headers=headers
    )

    assert cancelled.json()["data"]["status"] == "cancelled"

    # The worker is not interrupted mid-COM-call; it finds out here.
    progress = await client.post(
        f"/worker/jobs/{execution['id']}/progress",
        json={"step": "refresh_started"},
        headers=worker_auth,
    )

    assert progress.status_code == 409


@pytest.mark.asyncio
async def test_queue_is_empty_when_no_work_exists(client, db_session):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, _ = await worker_headers(client, headers)

    assert await claim(client, worker_auth) is None


@pytest.mark.asyncio
async def test_run_now_refuses_when_no_capable_worker_exists(
    client, db_session
):
    """Better a specific error now than a job that sits until it times out."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    # Enrolled, but its probe never confirmed PDF export.
    await worker_headers(
        client, headers, capabilities=["excel", "pafe_automation", "xlsx_export"]
    )

    workbook = await upload_workbook(client, headers)
    report = await create_report(
        client, headers, workbook["id"], output_formats=["pdf"]
    )

    response = await client.post(
        f"/reports/definitions/{report['id']}/run", headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKER_CAPABILITY_MISSING"


@pytest.mark.asyncio
async def test_worker_is_not_offered_work_it_cannot_do(client, db_session):
    """Capability filtering happens in the claim query itself."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    # A capable worker exists, so the PDF report can be queued...
    capable_auth, _ = await worker_headers(client, headers)

    workbook = await upload_workbook(client, headers)
    report = await create_report(
        client, headers, workbook["id"], output_formats=["pdf"]
    )

    await run_now(client, headers, report["id"])

    # ...but this one never proved PDF export and must not receive it.
    limited_auth, _ = await worker_headers(
        client, headers, capabilities=["excel", "pafe_automation", "xlsx_export"]
    )

    assert await claim(client, limited_auth) is None

    # The capable worker still gets it.
    assert await claim(client, capable_auth) is not None
