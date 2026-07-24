import uuid

import pytest

import src.services.auth_service as auth_service_module
from src.repositories.user_repository import user_repository
from tests.fixtures.factories import DEFAULT_PASSWORD, create_organization


async def _register_and_approve(
    client,
    db_session,
    org,
    username: str,
    email: str,
    password: str = DEFAULT_PASSWORD,
):
    """Registers via the real endpoint (so request payload shape stays
    honest) then approves directly via the ORM — most of these tests are
    about login/refresh/reset/Google sign-in mechanics, not the approval
    workflow itself (that gets its own dedicated tests below)."""

    resp = await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
            "organization_code": org.code,
        },
    )
    assert resp.status_code == 201

    user = await user_repository.get_by_username(db_session, username)
    user.registration_status = "approved"
    await user_repository.update(db_session, user)

    return resp


class FakeEmailProvider:

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, *, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def fake_email_provider(monkeypatch):
    provider = FakeEmailProvider()
    monkeypatch.setattr(
        auth_service_module, "get_email_provider", lambda: provider
    )
    return provider


@pytest.mark.asyncio
async def test_register_creates_an_approved_account(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]

    register_resp = await client.post(
        "/auth/register",
        json={
            "username": f"user_{suffix}",
            "email": f"user_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_code": org.code,
        },
    )
    assert register_resp.status_code == 201
    body = register_resp.json()
    assert body["success"] is True
    assert body["data"]["username"] == f"user_{suffix}"
    assert body["data"]["registration_status"] == "approved"


@pytest.mark.asyncio
async def test_register_without_organization_code_uses_default_org(
    client, db_session
):
    suffix = uuid.uuid4().hex[:8]

    register_resp = await client.post(
        "/auth/register",
        json={
            "username": f"user_{suffix}",
            "email": f"user_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert register_resp.status_code == 201
    assert register_resp.json()["data"]["registration_status"] == "approved"

    # Registering a second user with no code lands in the same default org
    # rather than creating a new one each time.
    suffix2 = uuid.uuid4().hex[:8]
    second_resp = await client.post(
        "/auth/register",
        json={
            "username": f"user_{suffix2}",
            "email": f"user_{suffix2}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert second_resp.status_code == 201

    first_user = await user_repository.get_by_username(db_session, f"user_{suffix}")
    second_user = await user_repository.get_by_username(db_session, f"user_{suffix2}")
    assert first_user.organization_id == second_user.organization_id


@pytest.mark.asyncio
async def test_register_then_login_succeeds_immediately(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    username = f"user_{suffix}"

    await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"user_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_code": org.code,
        },
    )

    login_resp = await client.post(
        "/auth/login",
        json={"username": username, "password": DEFAULT_PASSWORD},
    )
    assert login_resp.status_code == 200
    login_body = login_resp.json()
    assert login_body["success"] is True
    assert "access_token" in login_body["data"]

    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {login_body['data']['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["username"] == username


@pytest.mark.asyncio
async def test_login_rejected_after_registration_rejected(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    username = f"user_{suffix}"

    await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"user_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_code": org.code,
        },
    )

    user = await user_repository.get_by_username(db_session, username)
    user.registration_status = "rejected"
    await user_repository.update(db_session, user)

    resp = await client.post(
        "/auth/login",
        json={"username": username, "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 403
    assert "not approved" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_register_rejects_unknown_organization_code(client, db_session):
    suffix = uuid.uuid4().hex[:8]

    resp = await client.post(
        "/auth/register",
        json={
            "username": f"user_{suffix}",
            "email": f"user_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_code": "no-such-org-code",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_username_conflict(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "username": f"dup_{suffix}",
        "email": f"dup_{suffix}@example.com",
        "password": DEFAULT_PASSWORD,
        "first_name": "Test",
        "last_name": "User",
        "organization_code": org.code,
    }

    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    payload["email"] = f"dup2_{suffix}@example.com"
    second = await client.post("/auth/register", json=payload)

    assert second.status_code == 409
    body = second.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_login_wrong_password(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]

    await _register_and_approve(
        client, db_session, org, f"user_{suffix}", f"user_{suffix}@example.com"
    )

    resp = await client.post(
        "/auth/login",
        json={"username": f"user_{suffix}", "password": "WrongPassword"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_ERROR"


@pytest.mark.asyncio
async def test_refresh_endpoint_issues_a_new_access_token(client, db_session):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]

    await _register_and_approve(
        client, db_session, org, f"user_{suffix}", f"user_{suffix}@example.com"
    )

    login_resp = await client.post(
        "/auth/login",
        json={"username": f"user_{suffix}", "password": DEFAULT_PASSWORD},
    )
    tokens = login_resp.json()["data"]

    refresh_resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()["data"]
    assert new_tokens["access_token"] != tokens["access_token"]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["username"] == f"user_{suffix}"


@pytest.mark.asyncio
async def test_refresh_endpoint_rejects_invalid_token(client, db_session):
    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": "not-a-real-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_ERROR"


@pytest.mark.asyncio
async def test_forgot_and_reset_password_end_to_end(
    client, db_session, fake_email_provider
):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    email = f"user_{suffix}@example.com"

    await _register_and_approve(client, db_session, org, f"user_{suffix}", email)

    forgot_resp = await client.post("/auth/forgot-password", json={"email": email})
    assert forgot_resp.status_code == 200
    assert forgot_resp.json()["success"] is True

    assert len(fake_email_provider.sent) == 1
    raw_token = fake_email_provider.sent[0]["body"].split("token=")[1].split()[0]

    reset_resp = await client.post(
        "/auth/reset-password",
        json={"token": raw_token, "new_password": "BrandNewPassword123!"},
    )
    assert reset_resp.status_code == 200

    old_login = await client.post(
        "/auth/login",
        json={"username": f"user_{suffix}", "password": DEFAULT_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/auth/login",
        json={"username": f"user_{suffix}", "password": "BrandNewPassword123!"},
    )
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_forgot_password_returns_success_for_unknown_email(
    client, db_session, fake_email_provider
):
    resp = await client.post(
        "/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert fake_email_provider.sent == []


@pytest.mark.asyncio
async def test_reset_password_rejects_invalid_token(client, db_session):
    resp = await client.post(
        "/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "BrandNewPassword123!"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_ERROR"


@pytest.mark.asyncio
async def test_google_login_issues_tokens_for_existing_account(
    client, db_session, monkeypatch
):
    org = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    email = f"googleuser_{suffix}@example.com"

    await _register_and_approve(
        client, db_session, org, f"googleuser_{suffix}", email
    )

    monkeypatch.setattr(
        auth_service_module,
        "verify_google_id_token",
        lambda token: {"email": email, "email_verified": True},
    )

    resp = await client.post("/auth/google", json={"id_token": "fake-token"})

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "access_token" in body

    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["data"]["email"] == email


@pytest.mark.asyncio
async def test_google_login_auto_creates_account_for_new_email(
    client, db_session, monkeypatch
):
    suffix = uuid.uuid4().hex[:8]
    email = f"newgoogleuser_{suffix}@example.com"

    monkeypatch.setattr(
        auth_service_module,
        "verify_google_id_token",
        lambda token: {
            "email": email,
            "email_verified": True,
            "given_name": "New",
            "family_name": "Googler",
        },
    )

    resp = await client.post("/auth/google", json={"id_token": "fake-token"})

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "access_token" in body

    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()["data"]
    assert me_data["email"] == email
    assert me_data["first_name"] == "New"
    assert me_data["last_name"] == "Googler"


@pytest.mark.asyncio
async def test_google_login_reuses_account_on_second_login(
    client, db_session, monkeypatch
):
    suffix = uuid.uuid4().hex[:8]
    email = f"repeatgoogleuser_{suffix}@example.com"

    monkeypatch.setattr(
        auth_service_module,
        "verify_google_id_token",
        lambda token: {"email": email, "email_verified": True},
    )

    first_resp = await client.post("/auth/google", json={"id_token": "fake-token"})
    second_resp = await client.post("/auth/google", json={"id_token": "fake-token"})

    assert first_resp.status_code == 200
    assert second_resp.status_code == 200

    first_me = await client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {first_resp.json()['data']['access_token']}"
        },
    )
    second_me = await client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {second_resp.json()['data']['access_token']}"
        },
    )
    assert first_me.json()["data"]["id"] == second_me.json()["data"]["id"]
