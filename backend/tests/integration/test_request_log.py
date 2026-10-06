"""Every request a person makes is recorded — never its body or a secret."""

import pytest

from src.database.models.request_log import RequestLog
from src.middleware import request_log
from tests.fixtures.factories import DEFAULT_PASSWORD, auth_headers, create_org_admin, create_organization, create_user, grant_system_role


@pytest.fixture
def written(monkeypatch):
    rows: list[dict] = []

    async def capture(entry: dict) -> None:
        rows.append(entry)

    monkeypatch.setattr(request_log, "write_request_log", capture)
    return rows


@pytest.mark.asyncio
async def test_a_request_is_recorded_with_who_what_and_how_it_ended(client, db_session, written):
    _org, person = await create_org_admin(db_session)

    resp = await client.get("/auth/me", headers={**auth_headers(person), "user-agent": "pytest-browser"})
    assert resp.status_code == 200

    [entry] = [r for r in written if r["path"] == "/auth/me"]
    assert entry["user_id"] == person.id
    assert entry["method"] == "GET" and entry["route"] == "/auth/me"
    assert entry["status_code"] == 200 and entry["duration_ms"] >= 0
    assert entry["user_agent"] == "pytest-browser"
    assert entry["request_id"]


@pytest.mark.asyncio
async def test_a_sign_in_is_recorded_without_its_password(client, db_session, written):
    _org, person = await create_org_admin(db_session)
    await db_session.commit()

    db_session.info.pop("organization_id", None)
    await client.post("/auth/login", json={"username": person.username, "password": DEFAULT_PASSWORD})

    [entry] = [r for r in written if r["path"] == "/auth/login"]
    assert entry["user_id"] is None  # no token on the way in
    assert DEFAULT_PASSWORD not in repr(entry)


@pytest.mark.asyncio
async def test_secrets_in_a_query_string_are_redacted(client, written):
    await client.get("/auth/me?token=abc123&page=2")
    [entry] = [r for r in written if r["path"].startswith("/auth/me")]
    assert "abc123" not in entry["path"] and "page=2" in entry["path"]
    assert entry["status_code"] in (401, 403)


@pytest.mark.asyncio
async def test_machine_traffic_is_left_out(client, written):
    await client.get("/health")
    await client.options("/auth/me")
    assert written == []


@pytest.mark.asyncio
async def test_a_failure_to_record_never_fails_the_request(client, db_session, monkeypatch):
    async def broken(entry: dict) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(request_log, "write_request_log", broken)
    _org, person = await create_org_admin(db_session)
    resp = await client.get("/auth/me", headers=auth_headers(person))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_the_super_admin_reads_requests_and_failed_ones(client, db_session, written):
    org = await create_organization(db_session)
    boss = await create_user(db_session, org.id)
    await grant_system_role(db_session, boss.id, "Super Admin")
    db_session.add_all([
        RequestLog(user_id=boss.id, method="GET", path="/tm1/connections", route="/tm1/connections",
                   status_code=200, duration_ms=12),
        RequestLog(user_id=boss.id, method="DELETE", path="/knowledge/documents/x", route="/knowledge/documents/{id}",
                   status_code=404, duration_ms=5),
    ])
    await db_session.flush()

    resp = await client.get(f"/admin/platform/requests?user_id={boss.id}&failed_only=true", headers=auth_headers(boss))
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert [r["method"] for r in rows] == ["DELETE"]
    assert rows[0]["user"]["email"] == boss.email

    activity = await client.get(f"/admin/platform/users/{boss.id}/activity", headers=auth_headers(boss))
    assert {r["path"] for r in activity.json()["data"]["requests"]} >= {"/tm1/connections", "/knowledge/documents/x"}
