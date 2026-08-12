"""Shared setup for report automation API tests.

Everything here drives the real HTTP surface rather than the services, so
the tests exercise permission checks, tenancy resolution and serialization
the same way a real caller would.
"""

import uuid

WORKBOOK_BYTES = b"PK\x03\x04" + b"\x00" * 512

FULL_CAPABILITIES = ["excel", "pafe_automation", "xlsx_export", "pdf_export"]


async def register_worker(client, headers, name: str | None = None) -> dict:
    """Create a worker slot; returns the console response payload."""

    response = await client.post(
        "/reports/workers",
        json={"name": name or f"worker-{uuid.uuid4().hex[:8]}"},
        headers=headers,
    )

    assert response.status_code == 201, response.text

    return response.json()["data"]


async def enroll_worker(
    client,
    enrollment_token: str,
    capabilities: list[str] | None = None,
) -> dict:
    """Complete enrollment as the worker process would."""

    response = await client.post(
        "/worker/enroll",
        json={
            "enrollment_token": enrollment_token,
            "host": {
                "version": "0.1.0",
                "os": "Windows 11",
                "hostname": "test-host",
                "excel_version": "16.0",
                "pafe_version": "2.0.99.1",
                "capabilities": (
                    FULL_CAPABILITIES if capabilities is None else capabilities
                ),
            },
        },
    )

    assert response.status_code == 200, response.text

    return response.json()["data"]


async def worker_token(client, worker_id: str, secret: str) -> str:
    response = await client.post(
        "/worker/token",
        json={"worker_id": worker_id, "worker_secret": secret},
    )

    assert response.status_code == 200, response.text

    return response.json()["data"]["access_token"]


async def worker_headers(client, headers, capabilities=None) -> tuple[dict, str]:
    """Register + enroll + authenticate in one step.

    Returns (auth headers for the worker plane, worker id).
    """

    registered = await register_worker(client, headers)

    enrolled = await enroll_worker(
        client, registered["enrollment_token"], capabilities
    )

    token = await worker_token(
        client, enrolled["worker_id"], enrolled["worker_secret"]
    )

    return {"Authorization": f"Bearer {token}"}, enrolled["worker_id"]


async def upload_workbook(
    client,
    headers,
    *,
    filename: str = "Monthly P&L.xlsx",
    content: bytes | None = None,
) -> dict:
    response = await client.post(
        "/reports/workbooks",
        files={
            "file": (
                filename,
                content if content is not None else WORKBOOK_BYTES,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text

    return response.json()["data"]


async def create_report(
    client,
    headers,
    workbook_id: str,
    *,
    name: str | None = None,
    output_formats: list[str] | None = None,
    worker_id: str | None = None,
) -> dict:
    payload = {
        "name": name or f"Report {uuid.uuid4().hex[:6]}",
        "report_type": "pafe_workbook",
        "workbook_id": workbook_id,
        "output_formats": output_formats or ["xlsx"],
    }

    if worker_id:
        payload["worker_id"] = worker_id

    response = await client.post(
        "/reports/definitions", json=payload, headers=headers
    )

    assert response.status_code == 201, response.text

    return response.json()["data"]


async def run_now(client, headers, report_id: str) -> dict:
    response = await client.post(
        f"/reports/definitions/{report_id}/run", headers=headers
    )

    assert response.status_code == 201, response.text

    return response.json()["data"]


async def claim(client, worker_auth) -> dict | None:
    response = await client.post("/worker/jobs/claim", headers=worker_auth)

    assert response.status_code == 200, response.text

    return response.json()["data"]


async def setup_runnable_report(client, headers) -> tuple[dict, dict, str]:
    """The common arrangement: an enrolled worker and a queued execution.

    Returns (worker auth headers, execution payload, report id).
    """

    worker_auth, _ = await worker_headers(client, headers)

    workbook = await upload_workbook(client, headers)
    report = await create_report(client, headers, workbook["id"])
    result = await run_now(client, headers, report["id"])

    return worker_auth, result["execution"], report["id"]
