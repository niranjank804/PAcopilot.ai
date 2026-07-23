import uuid

import pytest

from src.repositories.role_repository import role_repository
from src.repositories.user_repository import user_repository
from tests.fixtures.factories import (
    DEFAULT_PASSWORD,
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
    grant_system_role,
)


async def _register_pending(client, db_session, org, suffix: str):
    """Registration now auto-approves (testing-phase default) - these tests
    are about the approve/reject/deactivate endpoints themselves, which
    still need a genuinely pending account to exercise, so force it back
    to pending after registering rather than via the (now-unreachable
    through the API) pending-by-default path."""

    resp = await client.post(
        "/auth/register",
        json={
            "username": f"pending_{suffix}",
            "email": f"pending_{suffix}@example.com",
            "password": DEFAULT_PASSWORD,
            "first_name": "Pending",
            "last_name": "User",
            "organization_code": org.code,
        },
    )
    assert resp.status_code == 201

    user = await user_repository.get_by_username(db_session, f"pending_{suffix}")
    user.registration_status = "pending"
    await user_repository.update(db_session, user)

    data = resp.json()["data"]
    data["registration_status"] = "pending"
    return data


@pytest.mark.asyncio
async def test_list_users_includes_pending_status_filter(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    suffix = uuid.uuid4().hex[:8]
    await _register_pending(client, db_session, org, suffix)

    resp = await client.get("/users?registration_status=pending", headers=headers)

    assert resp.status_code == 200
    usernames = [u["username"] for u in resp.json()["data"]]
    assert f"pending_{suffix}" in usernames


@pytest.mark.asyncio
async def test_approve_user_without_role_activates_login(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    suffix = uuid.uuid4().hex[:8]
    pending = await _register_pending(client, db_session, org, suffix)

    approve_resp = await client.post(
        f"/users/{pending['id']}/approve", json={}, headers=headers
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["data"]["registration_status"] == "approved"

    login_resp = await client.post(
        "/auth/login",
        json={"username": f"pending_{suffix}", "password": DEFAULT_PASSWORD},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_approve_user_with_role_assigns_it(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    suffix = uuid.uuid4().hex[:8]
    pending = await _register_pending(client, db_session, org, suffix)
    viewer_role = await role_repository.get_system_role(db_session, "Viewer")

    approve_resp = await client.post(
        f"/users/{pending['id']}/approve",
        json={"role_id": str(viewer_role.id)},
        headers=headers,
    )
    assert approve_resp.status_code == 200

    roles_resp = await client.get(
        f"/users/{pending['id']}/roles", headers=headers
    )
    assert roles_resp.status_code == 200
    role_names = [r["name"] for r in roles_resp.json()["data"]]
    assert "Viewer" in role_names


@pytest.mark.asyncio
async def test_reject_user_blocks_login(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    suffix = uuid.uuid4().hex[:8]
    pending = await _register_pending(client, db_session, org, suffix)

    reject_resp = await client.post(f"/users/{pending['id']}/reject", headers=headers)
    assert reject_resp.status_code == 200
    assert reject_resp.json()["data"]["registration_status"] == "rejected"

    login_resp = await client.post(
        "/auth/login",
        json={"username": f"pending_{suffix}", "password": DEFAULT_PASSWORD},
    )
    assert login_resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_already_decided_user_is_a_conflict(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    suffix = uuid.uuid4().hex[:8]
    pending = await _register_pending(client, db_session, org, suffix)

    first = await client.post(f"/users/{pending['id']}/approve", json={}, headers=headers)
    assert first.status_code == 200

    second = await client.post(f"/users/{pending['id']}/approve", json={}, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_viewer_cannot_approve_users(client, db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")
    suffix = uuid.uuid4().hex[:8]
    pending = await _register_pending(client, db_session, org, suffix)

    resp = await client.post(
        f"/users/{pending['id']}/approve",
        json={},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_deactivate_then_activate_user(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    member = await create_user(db_session, org.id)
    # Captured now — a 403 response below rolls back the shared session's
    # savepoint, which expires this ORM object (see the auth_headers-reuse
    # gotcha documented for this test suite).
    member_id = member.id
    member_username = member.username

    deactivate_resp = await client.post(
        f"/users/{member_id}/deactivate", headers=headers
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["data"]["is_active"] is False

    login_resp = await client.post(
        "/auth/login",
        json={"username": member_username, "password": DEFAULT_PASSWORD},
    )
    assert login_resp.status_code == 403

    activate_resp = await client.post(
        f"/users/{member_id}/activate", headers=headers
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["data"]["is_active"] is True

    login_resp_2 = await client.post(
        "/auth/login",
        json={"username": member_username, "password": DEFAULT_PASSWORD},
    )
    assert login_resp_2.status_code == 200


@pytest.mark.asyncio
async def test_cannot_deactivate_own_account(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.post(f"/users/{admin.id}/deactivate", headers=headers)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_viewer_cannot_deactivate_users(client, db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")
    member = await create_user(db_session, org.id)

    resp = await client.post(
        f"/users/{member.id}/deactivate", headers=auth_headers(viewer)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_deactivate_a_user_in_another_organization(client, db_session):
    org_a, admin_a = await create_org_admin(db_session)
    org_b = await create_organization(db_session)
    member_b = await create_user(db_session, org_b.id)

    resp = await client.post(
        f"/users/{member_b.id}/deactivate", headers=auth_headers(admin_a)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_approve_a_user_in_another_organization(client, db_session):
    org_a, admin_a = await create_org_admin(db_session)
    org_b = await create_organization(db_session)
    suffix = uuid.uuid4().hex[:8]
    pending_in_b = await _register_pending(client, db_session, org_b, suffix)

    resp = await client.post(
        f"/users/{pending_in_b['id']}/approve",
        json={},
        headers=auth_headers(admin_a),
    )
    assert resp.status_code == 404
