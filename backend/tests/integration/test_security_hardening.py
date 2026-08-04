"""Phase 1 hardening. Each test pins a leak or an unbounded path shut."""

import pytest

from src.core.config import settings


# ---------------------------------------------------------------------------
# The database probe must not describe the server to anonymous callers.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_probe_reveals_nothing_about_the_server(client):
    response = await client.get("/database")

    assert response.status_code == 200

    body = response.json()

    assert body == {"status": "connected"}

    text = response.text.lower()

    # The exact patch level maps onto published CVEs; the database name and
    # any driver text (which carries host and username) are equally out.
    for leak in ("postgresql", "postgres", "enterprise_ai", "asyncpg", "host"):
        assert leak not in text, leak


@pytest.mark.asyncio
async def test_database_details_requires_an_administrator(client):
    response = await client.get("/database/details")

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_database_failure_never_returns_the_driver_message(
    client, monkeypatch
):
    import src.api.v1.database as database_module

    class Boom(Exception):
        def __str__(self):
            return (
                "connection failed: host=db.internal port=5432 "
                "user=pa_copilot password=hunter2"
            )

    async def exploding_probe():
        raise Boom()

    class FailingSession:
        async def __aenter__(self):
            await exploding_probe()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        database_module, "AsyncSessionLocal", lambda: FailingSession()
    )

    response = await client.get("/database")

    assert response.json() == {"status": "unavailable"}

    for secret in ("db.internal", "pa_copilot", "hunter2", "5432"):
        assert secret not in response.text, secret


# ---------------------------------------------------------------------------
# Interactive docs enumerate the whole attack surface.
# ---------------------------------------------------------------------------


def test_docs_exposure_follows_debug():
    # Derived, not independently set, so a production deploy cannot leave
    # DEBUG off and the docs on by omission.
    assert settings.EXPOSE_API_DOCS == settings.DEBUG


def test_debug_is_not_hardcoded_in_the_app():
    from src.main import app

    assert app.debug == settings.DEBUG


# ---------------------------------------------------------------------------
# Unauthenticated endpoints are the credential-stuffing surface.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_failed_logins_are_throttled(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_ATTEMPTS_PER_WINDOW", 3)

    payload = {"username": "nobody", "password": "wrong"}

    for _ in range(3):
        response = await client.post("/auth/login", json=payload)
        assert response.status_code == 401, response.text

    throttled = await client.post("/auth/login", json=payload)

    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "RATE_LIMITED"
    # Without this a client retries immediately and is throttled again.
    assert "Retry-After" in throttled.headers


@pytest.mark.asyncio
async def test_password_reset_requests_are_throttled(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PASSWORD_RESET_PER_WINDOW", 2)

    payload = {"email": "someone@example.com"}

    for _ in range(2):
        assert (
            await client.post("/auth/forgot-password", json=payload)
        ).status_code == 200

    throttled = await client.post("/auth/forgot-password", json=payload)

    assert throttled.status_code == 429


@pytest.mark.asyncio
async def test_registration_is_throttled(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REGISTER_PER_WINDOW", 2)

    def body(n):
        return {
            "username": f"throttled{n}",
            "email": f"throttled{n}@example.com",
            "password": "Str0ngPassw0rd!",
            "first_name": "T",
            "last_name": "U",
        }

    for n in range(2):
        assert (await client.post("/auth/register", json=body(n))).status_code == 201

    assert (await client.post("/auth/register", json=body(99))).status_code == 429


@pytest.mark.asyncio
async def test_throttle_scopes_do_not_share_a_budget(client, monkeypatch):
    # Exhausting login must not lock out password reset: they are separate
    # abuse cases with separate budgets.
    monkeypatch.setattr(settings, "AUTH_LOGIN_ATTEMPTS_PER_WINDOW", 1)
    monkeypatch.setattr(settings, "AUTH_PASSWORD_RESET_PER_WINDOW", 5)

    await client.post("/auth/login", json={"username": "a", "password": "b"})
    assert (
        await client.post("/auth/login", json={"username": "a", "password": "b"})
    ).status_code == 429

    assert (
        await client.post(
            "/auth/forgot-password", json={"email": "x@example.com"}
        )
    ).status_code == 200
