"""Worker-plane rate limiting.

Every `/worker/*` route was previously unbounded. A worker is a machine
on a polling loop so its legitimate rate is high, but a stolen
credential could poll `claim` in a tight loop against the database.
"""

import pytest

from src.core import rate_limit
from src.core.config import settings
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.reports.helpers import register_worker, worker_headers


@pytest.mark.asyncio
async def test_authenticated_worker_calls_are_bounded(
    client, db_session, monkeypatch
):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, _ = await worker_headers(client, headers)

    # Tightened for the test; the real value is 120/min, chosen to leave
    # ~3x headroom over a busy worker's ~40 calls/min.
    monkeypatch.setattr(settings, "RATE_LIMIT_WORKER_PER_WINDOW", 3)
    rate_limit.reset()

    statuses = [
        (await client.post("/worker/jobs/claim", headers=worker_auth)).status_code
        for _ in range(5)
    ]

    assert 429 in statuses, "worker plane is unbounded"
    assert statuses.count(200) <= 3


@pytest.mark.asyncio
async def test_a_throttled_worker_is_told_when_to_retry(
    client, db_session, monkeypatch
):
    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    worker_auth, _ = await worker_headers(client, headers)

    monkeypatch.setattr(settings, "RATE_LIMIT_WORKER_PER_WINDOW", 1)
    rate_limit.reset()

    await client.post("/worker/jobs/claim", headers=worker_auth)
    response = await client.post("/worker/jobs/claim", headers=worker_auth)

    assert response.status_code == 429
    # Without Retry-After a client retries immediately and is throttled
    # again — the header is what makes backoff possible.
    assert "retry-after" in {k.lower() for k in response.headers}


@pytest.mark.asyncio
async def test_one_worker_does_not_exhaust_the_whole_organization(
    client, db_session, monkeypatch
):
    """Per-worker and per-organization windows are separate."""

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    first, _ = await worker_headers(client, headers)
    second, _ = await worker_headers(client, headers)

    monkeypatch.setattr(settings, "RATE_LIMIT_WORKER_PER_WINDOW", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WORKER_ORG_PER_WINDOW", 100)
    rate_limit.reset()

    for _ in range(4):
        await client.post("/worker/jobs/claim", headers=first)

    # The second worker still has its own allowance.
    response = await client.post("/worker/jobs/claim", headers=second)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_the_token_endpoint_is_throttled_by_ip(
    client, db_session, monkeypatch
):
    """The credential-guessing surface of the worker plane.

    /worker/token accepts a secret and answers whether it was right —
    the same shape of risk as /auth/login, and previously unbounded.
    """

    _, user = await create_org_admin(db_session)
    headers = auth_headers(user)

    registered = await register_worker(client, headers)
    worker_id = registered["worker"]["id"]

    monkeypatch.setattr(
        settings, "RATE_LIMIT_WORKER_CREDENTIAL_IP_PER_WINDOW", 3
    )
    rate_limit.reset()

    statuses = []

    for _ in range(6):
        response = await client.post(
            "/worker/token",
            json={"worker_id": worker_id, "worker_secret": "pacw-secret-wrong"},
        )
        statuses.append(response.status_code)

    # Guessing is bounded, not free.
    assert 429 in statuses, "credential endpoint is unbounded"


@pytest.mark.asyncio
async def test_the_enroll_endpoint_is_throttled_by_ip(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        settings, "RATE_LIMIT_WORKER_CREDENTIAL_IP_PER_WINDOW", 2
    )
    rate_limit.reset()

    statuses = []

    for _ in range(5):
        response = await client.post(
            "/worker/enroll",
            json={
                "enrollment_token": "pacw-enroll-guessing",
                "host": {"capabilities": []},
            },
        )
        statuses.append(response.status_code)

    assert 429 in statuses
