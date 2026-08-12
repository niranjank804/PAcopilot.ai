"""Adversarial tests — the 24 attack cases from the specification.

Each test names the attack and asserts the *specific* defence, not just
"it didn't work". Where the expected answer is 404 rather than 403 that
is deliberate and asserted: telling an attacker "that exists but isn't
yours" is itself a disclosure.
"""

import uuid

import pytest

from src.reports.worker_credentials import create_worker_token
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)
from tests.integration.reports.helpers import (
    claim,
    create_report,
    enroll_worker,
    register_worker,
    run_now,
    setup_runnable_report,
    upload_workbook,
    worker_headers,
    worker_token,
)


# ======================================================================
# 1-3: Cross-tenant access
# ======================================================================


@pytest.mark.asyncio
async def test_01_worker_cannot_claim_another_organizations_job(
    client, db_session
):
    """Attack: a worker in org A polls while org B has queued work."""

    _, user_a = await create_org_admin(db_session)
    _, user_b = await create_org_admin(db_session)

    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    # Org B queues a job.
    await setup_runnable_report(client, headers_b)

    # Org A's worker polls. The queue it sees is scoped by the server
    # from its own worker row, not by anything it sent.
    worker_a_auth, _ = await worker_headers(client, headers_a)

    assert await claim(client, worker_a_auth) is None


@pytest.mark.asyncio
async def test_02_worker_cannot_touch_another_organizations_execution(
    client, db_session
):
    """Attack: worker A addresses org B's execution by id directly."""

    _, user_a = await create_org_admin(db_session)
    _, user_b = await create_org_admin(db_session)

    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    _, execution_b, _ = await setup_runnable_report(client, headers_b)
    worker_a_auth, _ = await worker_headers(client, headers_a)

    execution_id = execution_b["id"]

    # Every worker-plane route that takes an execution id.
    for method, path, kwargs in (
        ("GET", f"/worker/jobs/{execution_id}/workbook", {}),
        ("POST", f"/worker/jobs/{execution_id}/start", {"json": {}}),
        ("POST", f"/worker/jobs/{execution_id}/progress", {"json": {"step": "x"}}),
        ("POST", f"/worker/jobs/{execution_id}/complete", {"json": {}}),
        (
            "POST",
            f"/worker/jobs/{execution_id}/fail",
            {"json": {"error_code": "internal_error"}},
        ),
    ):
        response = await client.request(
            method, path, headers=worker_a_auth, **kwargs
        )

        # 404, not 403: confirming the row exists elsewhere is a leak.
        assert response.status_code == 404, f"{method} {path}"


@pytest.mark.asyncio
async def test_03_user_cannot_read_another_organizations_report(
    client, db_session
):
    _, user_a = await create_org_admin(db_session)
    _, user_b = await create_org_admin(db_session)

    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    workbook_b = await upload_workbook(client, headers_b)
    report_b = await create_report(client, headers_b, workbook_b["id"])

    for path in (
        f"/reports/definitions/{report_b['id']}",
        f"/reports/definitions/{report_b['id']}/executions",
    ):
        response = await client.get(path, headers=headers_a)

        assert response.status_code == 404, path

    # ...and cannot run it either.
    response = await client.post(
        f"/reports/definitions/{report_b['id']}/run", headers=headers_a
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_03b_user_cannot_download_another_organizations_artifact(
    client, db_session
):
    """Attack: artifact id leaks; is it a bearer capability?"""

    _, user_a = await create_org_admin(db_session)
    _, user_b = await create_org_admin(db_session)

    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    worker_b_auth, execution_b, _ = await setup_runnable_report(
        client, headers_b
    )

    await claim(client, worker_b_auth)
    await client.post(
        f"/worker/jobs/{execution_b['id']}/start", headers=worker_b_auth
    )
    await client.post(
        f"/worker/jobs/{execution_b['id']}/artifacts",
        files={"file": ("o.xlsx", b"PK\x03\x04secret-financials", "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_b_auth,
    )

    detail = await client.get(
        f"/reports/executions/{execution_b['id']}", headers=headers_b
    )
    artifact_id = detail.json()["data"]["artifacts"][0]["id"]

    # Org A holds a valid session and the exact artifact id.
    response = await client.get(
        f"/reports/artifacts/{artifact_id}/download", headers=headers_a
    )

    assert response.status_code == 404
    assert b"secret-financials" not in response.content


# ======================================================================
# 4-6: Duplicate work
# ======================================================================


@pytest.mark.asyncio
async def test_04_two_workers_cannot_claim_the_same_execution(
    client, db_session
):
    """Attack: two workers race for one queued job."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_one, _ = await worker_headers(client, headers)
    worker_two, _ = await worker_headers(client, headers)

    workbook = await upload_workbook(client, headers)
    report = await create_report(client, headers, workbook["id"])
    result = await run_now(client, headers, report["id"])

    first = await claim(client, worker_one)
    second = await claim(client, worker_two)

    # Exactly one winner; SKIP LOCKED gives the loser nothing rather
    # than the same row.
    assert first is not None
    assert first["execution_id"] == result["execution"]["id"]
    assert second is None


@pytest.mark.asyncio
async def test_05_run_now_twice_creates_one_execution(client, db_session):
    """Attack: double-clicked Run, or a client retrying a slow request."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    await worker_headers(client, headers)

    workbook = await upload_workbook(client, headers)
    report = await create_report(client, headers, workbook["id"])

    first = await run_now(client, headers, report["id"])
    second = await run_now(client, headers, report["id"])

    assert first["created"] is True
    assert second["created"] is False
    assert first["execution"]["id"] == second["execution"]["id"]

    listed = await client.get(
        f"/reports/definitions/{report['id']}/executions", headers=headers
    )

    assert len(listed.json()["data"]) == 1


@pytest.mark.asyncio
async def test_06_same_artifact_uploaded_twice_is_stored_once(
    client, db_session
):
    """Attack/reality: upload succeeded but the response was lost."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    content = b"PK\x03\x04identical-output"

    def upload():
        return client.post(
            f"/worker/jobs/{execution['id']}/artifacts",
            files={"file": ("o.xlsx", content, "application/octet-stream")},
            data={"output_format": "xlsx"},
            headers=worker_auth,
        )

    first = await upload()
    second = await upload()

    assert first.json()["data"]["created"] is True
    # Same bytes, same slot: recognised as the retry it is.
    assert second.json()["data"]["created"] is False
    assert first.json()["data"]["artifact_id"] == second.json()["data"]["artifact_id"]

    listed = await client.get(
        f"/reports/executions/{execution['id']}/artifacts", headers=headers
    )

    assert len(listed.json()["data"]) == 1


@pytest.mark.asyncio
async def test_06b_different_bytes_in_the_same_slot_is_a_conflict(
    client, db_session
):
    """Not a retry — someone is overwriting a delivered artifact."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    await client.post(
        f"/worker/jobs/{execution['id']}/artifacts",
        files={"file": ("o.xlsx", b"PK\x03\x04original", "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_auth,
    )

    response = await client.post(
        f"/worker/jobs/{execution['id']}/artifacts",
        files={"file": ("o.xlsx", b"PK\x03\x04tampered", "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_auth,
    )

    assert response.status_code == 409


# ======================================================================
# 7-11, 20-22: Failure and recovery
# ======================================================================


@pytest.mark.asyncio
async def test_07_22_worker_retries_complete_after_a_lost_response(
    client, db_session
):
    """Attack/reality: Excel succeeded, the network dropped, worker retries.

    Must be idempotent. Turning a completed run into a failure — and a
    duplicate re-run — because an ACK was lost is the worst outcome.
    """

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)
    await client.post(
        f"/worker/jobs/{execution['id']}/artifacts",
        files={"file": ("o.xlsx", b"PK\x03\x04out", "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_auth,
    )

    first = await client.post(
        f"/worker/jobs/{execution['id']}/complete", json={}, headers=worker_auth
    )
    second = await client.post(
        f"/worker/jobs/{execution['id']}/complete", json={}, headers=worker_auth
    )

    assert first.status_code == 200
    assert first.json()["data"]["already_recorded"] is False
    assert second.status_code == 200
    assert second.json()["data"]["already_recorded"] is True

    detail = await client.get(
        f"/reports/executions/{execution['id']}", headers=headers
    )

    assert detail.json()["data"]["status"] == "succeeded"
    assert len(detail.json()["data"]["artifacts"]) == 1


@pytest.mark.asyncio
async def test_08_a_worker_cannot_finish_a_job_it_does_not_hold(
    client, db_session
):
    """Attack: worker B completes the job worker A is running."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_a, _ = await worker_headers(client, headers)
    worker_b, _ = await worker_headers(client, headers)

    workbook = await upload_workbook(client, headers)
    report = await create_report(client, headers, workbook["id"])
    result = await run_now(client, headers, report["id"])
    execution_id = result["execution"]["id"]

    await claim(client, worker_a)

    # Same organization, wrong worker.
    for path, body in (
        (f"/worker/jobs/{execution_id}/start", {}),
        (f"/worker/jobs/{execution_id}/complete", {}),
        (f"/worker/jobs/{execution_id}/fail", {"error_code": "internal_error"}),
    ):
        response = await client.post(path, json=body, headers=worker_b)

        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_09_11_infrastructure_failures_are_classified_correctly(
    client, db_session
):
    """Excel crash / PAfE missing / TM1 down get the right retry class."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    cases = {
        "excel_crashed": "retryable",
        "excel_launch_failed": "retryable",
        "tm1_connection_failed": "retryable",
        "pafe_not_installed": "requires_human",
        "pafe_api_unavailable": "requires_human",
        "tm1_auth_failed": "requires_human",
        "workbook_checksum_mismatch": "non_retryable",
    }

    for error_code, expected in cases.items():
        worker_auth, execution, _ = await setup_runnable_report(client, headers)

        await claim(client, worker_auth)
        await client.post(
            f"/worker/jobs/{execution['id']}/start", headers=worker_auth
        )

        response = await client.post(
            f"/worker/jobs/{execution['id']}/fail",
            json={"error_code": error_code},
            headers=worker_auth,
        )

        assert response.json()["data"]["retry_class"] == expected, error_code


@pytest.mark.asyncio
async def test_20_21_upload_into_a_finished_execution_is_refused(
    client, db_session
):
    """Attack: a late worker attaches output to an already-failed run."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)
    await client.post(
        f"/worker/jobs/{execution['id']}/fail",
        json={"error_code": "workbook_invalid"},
        headers=worker_auth,
    )

    response = await client.post(
        f"/worker/jobs/{execution['id']}/artifacts",
        files={"file": ("o.xlsx", b"PK\x03\x04late", "application/octet-stream")},
        data={"output_format": "xlsx"},
        headers=worker_auth,
    )

    assert response.status_code == 409


# ======================================================================
# 12-14: Workbook integrity and hostile filenames
# ======================================================================


@pytest.mark.asyncio
async def test_12_checksum_travels_with_the_job_and_the_download(
    client, db_session
):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    job = await claim(client, worker_auth)

    download = await client.get(
        f"/worker/jobs/{execution['id']}/workbook", headers=worker_auth
    )

    import hashlib

    actual = hashlib.sha256(download.content).hexdigest()

    # Three-way agreement: job payload, response header, real bytes.
    assert job["workbook"]["checksum"] == actual
    assert download.headers["X-Workbook-Checksum"] == actual


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    [
        "report.xlsx.exe",
        "report\u202egpj.exe",
        'evil".xlsx\r\nX-Injected: yes',
        "report\x00.xlsx",
        "payload.exe",
        "macro.bas",
    ],
)
async def test_13_hostile_filenames_are_rejected(client, db_session, filename):
    """Names that can only be an attack are refused outright."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    response = await client.post(
        "/reports/workbooks",
        files={"file": (filename, b"PK\x03\x04" + b"\x00" * 100, "application/octet-stream")},
        headers=headers,
    )

    assert response.status_code == 422, filename


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    [
        "../../../windows/system32/evil.xlsx",
        "..\\..\\..\\evil.xlsx",
        "C:\\Windows\\System32\\drivers\\etc\\hosts.xlsx",
        "/etc/passwd.xlsx",
        "subdir/report.xlsx",
    ],
)
async def test_14_path_components_cannot_survive_an_upload(
    client, db_session, filename
):
    """A path is stripped to its basename, not rejected.

    Legacy browsers genuinely do submit a full local path, so refusing
    would break real uploads. The security property is not "requests
    containing paths are refused" — it is that **no path component can
    reach storage or the worker**, which is what this asserts. The worker
    additionally never uses this value to build a path at all; it names
    the file after the execution UUID.
    """

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    response = await client.post(
        "/reports/workbooks",
        files={"file": (filename, b"PK\x03\x04" + b"\x00" * 100, "application/octet-stream")},
        headers=headers,
    )

    assert response.status_code == 201, filename

    stored = response.json()["data"]["filename"]

    assert "/" not in stored
    assert "\\" not in stored
    assert ".." not in stored
    assert ":" not in stored
    assert stored.endswith(".xlsx")


@pytest.mark.asyncio
async def test_13b_non_workbook_content_is_rejected(client, db_session):
    """Attack: rename an executable to .xlsx and upload it."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    response = await client.post(
        "/reports/workbooks",
        files={
            "file": (
                "totally-a-report.xlsx",
                b"MZ\x90\x00\x03" + b"\x00" * 100,  # Windows PE
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=headers,
    )

    assert response.status_code == 422


# ======================================================================
# 15-19: Authorization and credentials
# ======================================================================


@pytest.mark.asyncio
async def test_15_run_now_requires_the_execute_permission(client, db_session):
    """Analyst can read reports but must not be able to start one."""

    org, admin = await create_org_admin(db_session)
    admin_headers = auth_headers(admin)

    await worker_headers(client, admin_headers)
    workbook = await upload_workbook(client, admin_headers)
    report = await create_report(client, admin_headers, workbook["id"])

    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")
    analyst_headers = auth_headers(analyst)

    # Reading is allowed...
    readable = await client.get(
        f"/reports/definitions/{report['id']}", headers=analyst_headers
    )

    assert readable.status_code == 200

    # ...running is not.
    response = await client.post(
        f"/reports/definitions/{report['id']}/run", headers=analyst_headers
    )

    assert response.status_code == 403
    assert "reports.execute" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_16_worker_registration_requires_workers_manage(
    client, db_session
):
    org, admin = await create_org_admin(db_session)

    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")

    response = await client.post(
        "/reports/workers",
        json={"name": "rogue-worker"},
        headers=auth_headers(analyst),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_17_a_disabled_worker_cannot_claim_or_authenticate(
    client, db_session
):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    registered = await register_worker(client, headers)
    enrolled = await enroll_worker(client, registered["enrollment_token"])
    token = await worker_token(
        client, enrolled["worker_id"], enrolled["worker_secret"]
    )
    worker_auth = {"Authorization": f"Bearer {token}"}

    disabled = await client.post(
        f"/reports/workers/{enrolled['worker_id']}/disable", headers=headers
    )

    assert disabled.status_code == 200

    # The already-issued token stops working immediately — the worker row
    # is re-checked on every request, not trusted for the token's life.
    response = await client.post("/worker/jobs/claim", headers=worker_auth)

    assert response.status_code == 401

    # And no new token can be minted.
    reauth = await client.post(
        "/worker/token",
        json={
            "worker_id": enrolled["worker_id"],
            "worker_secret": enrolled["worker_secret"],
        },
    )

    assert reauth.status_code == 401


@pytest.mark.asyncio
async def test_18_an_enrollment_token_is_single_use(client, db_session):
    """Attack: replay a captured enrollment token."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    registered = await register_worker(client, headers)
    token = registered["enrollment_token"]

    await enroll_worker(client, token)

    replayed = await client.post(
        "/worker/enroll",
        json={"enrollment_token": token, "host": {"capabilities": []}},
    )

    assert replayed.status_code == 401


@pytest.mark.asyncio
async def test_18b_an_invalid_enrollment_token_is_indistinguishable(
    client, db_session
):
    """Probing must not reveal whether a token ever existed."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    registered = await register_worker(client, headers)
    await enroll_worker(client, registered["enrollment_token"])

    spent = await client.post(
        "/worker/enroll",
        json={
            "enrollment_token": registered["enrollment_token"],
            "host": {"capabilities": []},
        },
    )
    never_existed = await client.post(
        "/worker/enroll",
        json={
            "enrollment_token": "pacw-enroll-does-not-exist",
            "host": {"capabilities": []},
        },
    )

    assert spent.status_code == never_existed.status_code == 401
    assert spent.json()["error"] == never_existed.json()["error"]


@pytest.mark.asyncio
async def test_19_rotating_a_credential_revokes_tokens_in_flight(
    client, db_session
):
    """Attack: a stolen worker token keeps working after rotation."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    registered = await register_worker(client, headers)
    enrolled = await enroll_worker(client, registered["enrollment_token"])
    stolen = await worker_token(
        client, enrolled["worker_id"], enrolled["worker_secret"]
    )
    stolen_auth = {"Authorization": f"Bearer {stolen}"}

    # Works before rotation.
    assert (
        await client.post("/worker/jobs/claim", headers=stolen_auth)
    ).status_code == 200

    rotated = await client.post(
        f"/reports/workers/{enrolled['worker_id']}/rotate", headers=headers
    )

    assert rotated.status_code == 200

    # The secret_version claim no longer matches the row.
    assert (
        await client.post("/worker/jobs/claim", headers=stolen_auth)
    ).status_code == 401

    # And the old credential cannot mint a new token.
    reauth = await client.post(
        "/worker/token",
        json={
            "worker_id": enrolled["worker_id"],
            "worker_secret": enrolled["worker_secret"],
        },
    )

    assert reauth.status_code == 401


@pytest.mark.asyncio
async def test_19b_a_forged_worker_token_is_rejected(client, db_session):
    """Attack: mint a token for a worker id in another organization."""

    _, user_a = await create_org_admin(db_session)
    _, user_b = await create_org_admin(db_session)

    headers_b = auth_headers(user_b)

    registered = await register_worker(client, headers_b)
    enrolled = await enroll_worker(client, registered["enrollment_token"])

    # A token whose `org` claim lies about which organization it belongs
    # to. The signature is valid; the claim is not.
    forged, _ = create_worker_token(
        worker_id=uuid.UUID(enrolled["worker_id"]),
        organization_id=user_a.organization_id,
        secret_version=1,
    )

    response = await client.post(
        "/worker/jobs/claim", headers={"Authorization": f"Bearer {forged}"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_19c_a_user_token_cannot_drive_the_worker_plane(
    client, db_session
):
    """Attack: reuse a normal user JWT against worker endpoints.

    Both families are signed with the same key, so only the `type` claim
    separates them.
    """

    _, user = await create_org_admin(db_session)

    response = await client.post("/worker/jobs/claim", headers=auth_headers(user))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_19d_a_worker_token_cannot_drive_the_user_api(
    client, db_session
):
    """And the reverse — the more dangerous direction."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, _ = await worker_headers(client, headers)

    for path in ("/reports/definitions", "/reports/workers", "/reports/executions"):
        response = await client.get(path, headers=worker_auth)

        assert response.status_code == 401, path


# ======================================================================
# 23-24: Injection through the job payload
# ======================================================================


@pytest.mark.asyncio
async def test_23_24_report_metadata_cannot_smuggle_commands_to_the_worker(
    client, db_session
):
    """Attack: hide VBA / a shell command in report name and parameters.

    The job payload must carry an allowlisted verb and typed data only —
    no field that a worker could be induced to execute.
    """

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, _ = await worker_headers(client, headers)
    workbook = await upload_workbook(client, headers)

    response = await client.post(
        "/reports/definitions",
        json={
            "name": "P&L =cmd|'/c calc'!A1",
            "description": "<script>alert(1)</script>",
            "report_type": "pafe_workbook",
            "workbook_id": workbook["id"],
            "output_formats": ["xlsx"],
            "parameters": {
                "operation": "EXECUTE_SCRIPT",
                "vba": "Shell(\"cmd.exe /c whoami\")",
                "macro": "Auto_Open",
                "command": "powershell -enc ZQBjAGgAbwA=",
                "script_path": "C:\\evil.bat",
            },
        },
        headers=headers,
    )

    assert response.status_code == 201

    report = response.json()["data"]

    await run_now(client, headers, report["id"])

    job = await claim(client, worker_auth)

    # The operation is derived server-side from the validated report type.
    assert job["operation"] == "REFRESH_WORKBOOK"

    # None of the injected keys reach the worker: the job schema has no
    # field that carries them.
    assert "parameters" not in job
    assert "vba" not in job
    assert "command" not in job
    assert "script_path" not in job

    payload = str(job)

    for smuggled in ("EXECUTE_SCRIPT", "Shell(", "powershell", "evil.bat", "Auto_Open"):
        assert smuggled not in payload, smuggled

    # The job is exactly the fixed, typed shape.
    assert set(job.keys()) == {
        "execution_id",
        "report_id",
        "correlation_id",
        "operation",
        "output_formats",
        "workbook",
        "connection",
        "timeout_seconds",
        "lease_seconds",
        "attempt",
    }


@pytest.mark.asyncio
async def test_24b_an_unknown_error_code_cannot_become_stored_free_text(
    client, db_session
):
    """Attack: inject SQL/HTML through the failure report."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, execution, _ = await setup_runnable_report(client, headers)

    await claim(client, worker_auth)
    await client.post(f"/worker/jobs/{execution['id']}/start", headers=worker_auth)

    await client.post(
        f"/worker/jobs/{execution['id']}/fail",
        json={"error_code": "'; DROP TABLE report_executions; --"},
        headers=worker_auth,
    )

    detail = await client.get(
        f"/reports/executions/{execution['id']}", headers=headers
    )
    body = detail.json()["data"]

    # Coerced to a known code; the message is ours, not the worker's.
    assert body["error_code"] == "internal_error"
    assert "DROP TABLE" not in (body["error_message"] or "")


@pytest.mark.asyncio
async def test_unauthenticated_access_is_refused_everywhere(client, db_session):
    """Baseline: no endpoint on either plane is open."""

    for method, path in (
        ("GET", "/reports/definitions"),
        ("POST", "/reports/definitions"),
        ("GET", "/reports/workers"),
        ("POST", "/reports/workers"),
        ("GET", "/reports/executions"),
        ("POST", "/worker/jobs/claim"),
        ("POST", "/worker/heartbeat"),
    ):
        response = await client.request(method, path)

        assert response.status_code in (401, 403), f"{method} {path}"
