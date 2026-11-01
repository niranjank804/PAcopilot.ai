"""A Super Admin hands a locked-out person a one-time password (Platform →
Users) when no reset email can reach them. It is shown once, to the Super
Admin only; it signs in for a limited time; and it buys exactly one thing:
setting a password of one's own. The audit log says it happened, never
what the password was."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from src.core.config import settings
from src.database.models.audit_log import AuditLog
from src.database.models.user import User
from tests.fixtures.factories import (
    DEFAULT_PASSWORD,
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
    grant_system_role,
)

NEW_PASSWORD = "Chosen-by-me-2026"


async def _super_admin(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    await grant_system_role(db_session, user.id, "Super Admin")
    return user


async def _person(db_session):
    """Someone in another organization, with their id and username read
    before any request commits and expires the row."""

    _org, person = await create_org_admin(db_session)
    found = person, person.id, person.username
    # Committed: a refused request rolls the shared test session back, and
    # would take uncommitted rows with it.
    await db_session.commit()
    return found


async def _issue(client, admin, person_id, reason="asked by phone; no email reaches them"):
    headers = admin if isinstance(admin, dict) else auth_headers(admin)
    return await client.post(
        f"/admin/platform/users/{person_id}/temporary-password",
        json={"reason": reason},
        headers=headers,
    )


async def _login(client, username, password, db_session=None):
    return await client.post("/auth/login", json={"username": username, "password": password})


def _bearer(login_response) -> dict:
    return {"Authorization": f"Bearer {login_response.json()['data']['access_token']}"}


async def _audit_rows(db_session, action, entity_id):
    db_session.info.pop("organization_id", None)
    return (await db_session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
    )).scalars().all()


@pytest.fixture(autouse=True)
def _fresh_tenancy_per_request(db_session, monkeypatch):
    """The suite shares one session across requests; a real request gets
    its own, with no organization stamped before it authenticates."""

    from httpx2 import AsyncClient

    original = AsyncClient.request

    async def request(self, *args, **kwargs):
        db_session.info.pop("organization_id", None)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncClient, "request", request)


@pytest.mark.asyncio
async def test_only_a_super_admin_can_issue_one(client, db_session):
    _org, org_admin = await create_org_admin(db_session)
    person, person_id, username = await _person(db_session)

    resp = await _issue(client, org_admin, person_id)
    assert resp.status_code == 403, resp.text

    # Nothing changed for the person.
    assert (await _login(client, username, DEFAULT_PASSWORD)).status_code == 200


@pytest.mark.asyncio
async def test_it_is_shown_once_and_never_written_to_the_audit_log(client, db_session):
    admin = await _super_admin(db_session)
    person, person_id, username = await _person(db_session)
    old_session = auth_headers(person)

    resp = await _issue(client, admin, person_id, reason="locked out")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    password = data["temporary_password"]
    assert data["username"] == username
    # Readable over the phone: three groups of five, no ambiguous letters.
    groups = password.split("-")
    assert len(groups) == 3 and all(len(g) == 5 for g in groups)
    assert not set(password) & set("0O1lI-") - {"-"}
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    expected = datetime.now(UTC) + timedelta(hours=settings.TEMPORARY_PASSWORD_EXPIRE_HOURS)
    assert abs((expires - expected).total_seconds()) < 60

    rows = await _audit_rows(db_session, "platform_temporary_password", person_id)
    assert len(rows) == 1
    recorded = json.dumps(rows[0].new_values)
    assert rows[0].new_values["reason"] == "locked out"
    assert "expires_at" in rows[0].new_values
    assert password not in recorded and password.replace("-", "") not in recorded

    # The old password and every earlier session are finished.
    assert (await _login(client, username, DEFAULT_PASSWORD)).status_code == 401
    assert (await client.get("/auth/me", headers=old_session)).status_code == 401


@pytest.mark.asyncio
async def test_signing_in_with_it_allows_only_setting_a_new_password(client, db_session):
    admin = await _super_admin(db_session)
    person, person_id, username = await _person(db_session)
    password = (await _issue(client, admin, person_id)).json()["data"]["temporary_password"]
    # Sessions issued in the same whole second as a revocation count as
    # revoked; in use, passing the password on takes far longer than that.
    await asyncio.sleep(1.05)

    signed_in = await _login(client, username, password)
    assert signed_in.status_code == 200, signed_in.text
    temporary = _bearer(signed_in)

    me = await client.get("/auth/me", headers=temporary)
    assert me.status_code == 200 and me.json()["data"]["must_change_password"] is True

    blocked = await client.get("/tm1/connections", headers=temporary)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    wrong = await client.post(
        "/auth/change-password",
        json={"current_password": "not-it", "new_password": NEW_PASSWORD},
        headers=temporary,
    )
    assert wrong.status_code == 422, wrong.text
    assert (await client.get("/auth/me", headers=temporary)).json()["data"]["must_change_password"] is True

    changed = await client.post(
        "/auth/change-password",
        json={"current_password": password, "new_password": NEW_PASSWORD},
        headers=temporary,
    )
    assert changed.status_code == 200, changed.text
    assert len(await _audit_rows(db_session, "password_changed", person_id)) == 1

    # The change ended every session, the temporary one included …
    assert (await client.get("/auth/me", headers=temporary)).status_code == 401
    # … and handed back a fresh one that works at once, in full.
    fresh = _bearer(changed)
    me = await client.get("/auth/me", headers=fresh)
    assert me.status_code == 200, me.text
    assert me.json()["data"]["must_change_password"] is False
    assert (await client.get("/tm1/connections", headers=fresh)).status_code == 200
    # The temporary password is gone; the chosen one signs in.
    assert (await _login(client, username, password)).status_code == 401
    assert (await _login(client, username, NEW_PASSWORD)).status_code == 200


@pytest.mark.asyncio
async def test_an_expired_temporary_password_does_not_sign_in(client, db_session):
    admin = await _super_admin(db_session)
    person, person_id, username = await _person(db_session)
    password = (await _issue(client, admin, person_id)).json()["data"]["temporary_password"]

    db_session.info.pop("organization_id", None)
    await db_session.execute(
        update(User).where(User.id == person_id)
        .values(temporary_password_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()

    refused = await _login(client, username, password)
    assert refused.status_code == 401, refused.text
    assert "expired" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_who_cannot_be_given_one(client, db_session):
    admin = await _super_admin(db_session)
    admin_id = admin.id
    other_admin = await _super_admin(db_session)
    other_admin_id = other_admin.id
    org = await create_organization(db_session)
    inactive = await create_user(db_session, org.id, is_active=False)
    inactive_id = inactive.id
    headers = auth_headers(admin)
    await db_session.commit()
    admin = headers

    assert (await _issue(client, admin, admin_id)).status_code == 422          # not yourself
    assert (await _issue(client, admin, other_admin_id)).status_code == 422    # not another Super Admin
    assert (await _issue(client, admin, inactive_id)).status_code == 422       # reactivate first
    assert (await _issue(client, admin, uuid.uuid4())).status_code == 404


@pytest.mark.asyncio
async def test_the_platform_list_shows_who_is_on_a_temporary_password(client, db_session):
    admin = await _super_admin(db_session)
    person, person_id, _username = await _person(db_session)
    assert (await _issue(client, admin, person_id)).status_code == 200

    rows = (await client.get("/admin/platform/users", headers=auth_headers(admin))).json()["data"]
    flagged = {row["id"]: row["must_change_password"] for row in rows}
    assert flagged[str(person_id)] is True
    assert flagged[str(admin.id)] is False
