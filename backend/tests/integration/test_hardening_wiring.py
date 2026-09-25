"""Controls that existed in the tree without being on the wire.

The security-headers and request-id middlewares were written months
before anything registered them; a TM1 connection could point at the
platform's own network; the expensive routes had no throttle. Each test
here fails against the tree as it was.
"""

import pytest

from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core import rate_limit
from src.core.config import settings
from tests.fixtures.factories import auth_headers, create_org_admin


@pytest.fixture
def tm1_credentials_key():
    """Saving a connection encrypts its password. Without a key the save
    fails, so the test would pass only where a developer's .env has one."""

    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.mark.asyncio
async def test_every_response_carries_the_hardening_headers(client):
    resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'none'" in resp.headers["Content-Security-Policy"]


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id(client):
    first = await client.get("/health")
    second = await client.get("/health")

    assert first.headers["X-Request-ID"]
    assert second.headers["X-Request-ID"]
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_a_caller_cannot_choose_its_own_request_id(client):
    """Adopting an inbound id on a public endpoint would let one client
    collide ids with another's request and muddle the log trail."""

    resp = await client.get("/health", headers={"X-Request-ID": "chosen-by-caller"})

    assert resp.headers["X-Request-ID"] != "chosen-by-caller"


@pytest.mark.asyncio
async def test_error_responses_carry_the_headers_too(client):
    resp = await client.get("/tm1/connections")  # no token

    assert resp.status_code in (401, 403)
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Request-ID"]


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "localhost"])
async def test_a_connection_cannot_point_at_the_platforms_own_network(
    client, db_session, monkeypatch, address
):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", False)
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Probe",
            "address": address,
            "port": 80,
            "ssl": False,
            "username": "x",
            "password": "y",
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 422
    assert "private network" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_self_hosted_deployment_can_allow_private_addresses(
    client, db_session, monkeypatch, tm1_credentials_key
):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", True)
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/tm1/connections",
        json={
            "name": "LAN",
            "address": "192.168.1.20",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_expensive_routes_have_their_own_budget(client, db_session, monkeypatch):
    """Corpus analysis, document parsing and metadata extraction cost
    seconds of CPU or money per call; they get a tighter window than the
    general API and do not spend the AI one."""

    monkeypatch.setattr(settings, "RATE_LIMIT_HEAVY_USER_PER_WINDOW", 1)
    rate_limit.reset()
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    export = [("files", ("Load.pro", b"#Section=Prolog\n", "text/plain"))]

    first = await client.post("/learning/report", files=export, headers=headers)
    second = await client.post("/learning/report", files=export, headers=headers)

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.headers.get("Retry-After")

    # The AI window was not touched by either call.
    chat = await client.get("/ai/agents", headers=headers)
    assert chat.status_code == 200
