"""The platform owner's view: who signs in, which connections exist and who
uses them, and the levers to stop misuse — never a credential."""

import uuid

import pytest
from sqlalchemy import select

from src.database.models.sign_in_event import SignInEvent
from src.database.models.tm1_connection import TM1Connection
from src.repositories.user_repository import user_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.exceptions import TM1ConnectionSuspendedError
from tests.fixtures.factories import (
    DEFAULT_PASSWORD,
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
    grant_system_role,
)

SECRET = "s3cret-tm1-password"


async def _super_admin(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    await grant_system_role(db_session, user.id, "Super Admin")
    return user


async def _connection(client, owner) -> dict:
    created = await client.post(
        "/tm1/connections",
        json={
            "name": f"server-{uuid.uuid4().hex[:6]}",
            "address": "tm1.customer.example.com",
            "port": 8010,
            "ssl": True,
            "username": "tm1admin",
            "password": SECRET,
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]


async def _events(db_session, **where):
    db_session.info.pop("organization_id", None)
    stmt = select(SignInEvent)
    for key, value in where.items():
        stmt = stmt.where(getattr(SignInEvent, key) == value)
    return (await db_session.execute(stmt)).scalars().all()


@pytest.mark.asyncio
async def test_a_sign_in_is_recorded_with_when_and_from_where(client, db_session):
    _org, person = await create_org_admin(db_session)
    await db_session.commit()

    db_session.info.pop("organization_id", None)
    resp = await client.post(
        "/auth/login",
        json={"username": person.username, "password": DEFAULT_PASSWORD},
        headers={"user-agent": "pytest-browser"},
    )
    assert resp.status_code == 200, resp.text

    [event] = await _events(db_session, user_id=person.id)
    assert event.success and event.method == "password"
    assert event.user_agent == "pytest-browser"
    refreshed = await user_repository.get_by_id(db_session, person.id)
    assert refreshed.last_login_at is not None and refreshed.last_seen_at is not None


@pytest.mark.asyncio
async def test_a_failed_sign_in_is_kept_although_the_request_fails(client, db_session):
    _org, person = await create_org_admin(db_session)
    await db_session.commit()

    db_session.info.pop("organization_id", None)
    resp = await client.post(
        "/auth/login", json={"username": person.username, "password": "wrong-password"}
    )
    assert resp.status_code == 401, resp.text

    [event] = await _events(db_session, user_id=person.id)
    assert not event.success
    assert "Invalid" in (event.reason or "")
    # The guessed password is never stored, only what was typed as the name.
    assert event.identifier == person.username


@pytest.mark.asyncio
async def test_only_the_super_admin_sees_the_platform(client, db_session):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    # Each refusal rolls the request back; keep the account across them.
    await db_session.commit()

    for path in ("/admin/platform/overview", "/admin/platform/users", "/admin/platform/connections",
                 "/admin/platform/sign-ins", "/admin/platform/audit"):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 403, (path, resp.text)


@pytest.mark.asyncio
async def test_connections_show_who_and_where_but_never_the_secret(client, db_session):
    boss = await _super_admin(db_session)
    _org, owner = await create_org_admin(db_session)
    connection = await _connection(client, owner)

    resp = await client.get("/admin/platform/connections", headers=auth_headers(boss))
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["data"] if r["id"] == connection["id"])
    assert row["address"] == "tm1.customer.example.com"
    assert row["tm1_user"] == "tm1admin"
    assert row["owner"]["email"] == owner.email
    assert not any("password" in key or "key" in key for key in row)
    assert SECRET not in resp.text

    users = await client.get("/admin/platform/users", headers=auth_headers(boss))
    assert users.status_code == 200, users.text
    me = next(r for r in users.json()["data"] if r["id"] == str(owner.id))
    assert me["connections_owned"] == 1
    assert me["connections_used_30d"] == 1  # creating it is recorded against it


@pytest.mark.asyncio
async def test_a_persons_activity_names_the_servers_they_used(client, db_session):
    boss = await _super_admin(db_session)
    _org, owner = await create_org_admin(db_session)
    connection = await _connection(client, owner)

    resp = await client.get(f"/admin/platform/users/{owner.id}/activity", headers=auth_headers(boss))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    created = next(e for e in data["events"] if e["action"] == "create_connection")
    assert created["connection"]["name"] == connection["name"]
    assert SECRET not in resp.text

    audit = await client.get("/admin/platform/audit", headers=auth_headers(boss))
    assert audit.status_code == 200, audit.text
    assert any(r["action"] == "create_connection" and r["connection"] == connection["name"]
               for r in audit.json()["data"])


@pytest.mark.asyncio
async def test_deactivating_someone_stops_them_at_once(client, db_session):
    boss = await _super_admin(db_session)
    _org, person = await create_org_admin(db_session)
    assert (await client.get("/auth/me", headers=auth_headers(person))).status_code == 200

    resp = await client.post(
        f"/admin/platform/users/{person.id}/deactivate", json={"reason": "abuse"}, headers=auth_headers(boss)
    )
    assert resp.status_code == 200, resp.text

    db_session.info.pop("organization_id", None)
    assert (await client.get("/auth/me", headers=auth_headers(person))).status_code in (401, 403)


@pytest.mark.asyncio
async def test_the_super_admin_cannot_lock_themselves_out(client, db_session):
    boss = await _super_admin(db_session)
    resp = await client.post(
        f"/admin/platform/users/{boss.id}/deactivate", json={}, headers=auth_headers(boss)
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_suspended_connection_cannot_be_used_by_anything(client, db_session):
    boss = await _super_admin(db_session)
    _org, owner = await create_org_admin(db_session)
    connection = await _connection(client, owner)

    resp = await client.post(
        f"/admin/platform/connections/{connection['id']}/suspend",
        json={"reason": "credentials shared outside the company"},
        headers=auth_headers(boss),
    )
    assert resp.status_code == 200, resp.text

    db_session.info.pop("organization_id", None)
    row = (await db_session.execute(
        select(TM1Connection).where(TM1Connection.id == uuid.UUID(connection["id"]))
    )).scalar_one()
    with pytest.raises(TM1ConnectionSuspendedError):
        await tm1_connection_manager.get_client(row)

    # The owner sees why, rather than a failure.
    listed = await client.get("/tm1/connections", headers=auth_headers(owner))
    mine = next(c for c in listed.json()["data"] if c["id"] == connection["id"])
    assert mine["suspended_reason"] == "credentials shared outside the company"

    resumed = await client.post(
        f"/admin/platform/connections/{connection['id']}/resume", json={}, headers=auth_headers(boss)
    )
    assert resumed.status_code == 200, resumed.text
    platform = await client.get("/admin/platform/connections", headers=auth_headers(boss))
    again = next(r for r in platform.json()["data"] if r["id"] == connection["id"])
    assert again["suspended_at"] is None
    # Suspending and resuming is administration, not use of the server.
    assert [p["email"] for p in again["used_by_30d"]] == [owner.email]


@pytest.mark.asyncio
async def test_me_reports_the_super_admin_role(client, db_session):
    boss = await _super_admin(db_session)
    resp = await client.get("/auth/me", headers=auth_headers(boss))
    assert "Super Admin" in resp.json()["data"]["roles"]


@pytest.mark.asyncio
async def test_the_overview_and_sign_in_list_show_failed_attempts(client, db_session):
    boss = await _super_admin(db_session)
    headers = auth_headers(boss)
    await db_session.commit()

    db_session.info.pop("organization_id", None)
    guess = f"nobody-{uuid.uuid4().hex[:6]}"
    failed = await client.post("/auth/login", json={"username": guess, "password": "x" * 12})
    assert failed.status_code == 401

    overview = await client.get("/admin/platform/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()["data"]["failed_sign_ins_24h"] >= 1

    listed = await client.get("/admin/platform/sign-ins?success=false", headers=headers)
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json()["data"] if r["identifier"] == guess)
    assert row["user"] is None and not row["success"]
