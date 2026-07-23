import pytest

from tests.fixtures.factories import auth_headers, create_org_admin


@pytest.mark.asyncio
async def test_create_and_get_role(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await client.post(
        "/roles",
        json={"name": "Custom Role", "description": "A custom role"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    role_id = create_resp.json()["data"]["id"]

    get_resp = await client.get(f"/roles/{role_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["name"] == "Custom Role"


@pytest.mark.asyncio
async def test_cross_org_role_access_is_404(client, db_session):
    org_a, admin_a = await create_org_admin(db_session)
    org_b, admin_b = await create_org_admin(db_session)
    headers_a = auth_headers(admin_a)
    headers_b = auth_headers(admin_b)

    create_resp = await client.post(
        "/roles",
        json={"name": "A's Role"},
        headers=headers_a,
    )
    role_id = create_resp.json()["data"]["id"]

    get_resp = await client.get(f"/roles/{role_id}", headers=headers_b)
    assert get_resp.status_code == 404
    assert get_resp.json()["error"]["code"] == "NOT_FOUND"

    delete_resp = await client.delete(f"/roles/{role_id}", headers=headers_b)
    assert delete_resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401(client):
    resp = await client.get("/roles")
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_system_role_cannot_be_mutated(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    roles_resp = await client.get("/roles", headers=headers)
    viewer = next(r for r in roles_resp.json()["data"] if r["name"] == "Viewer")

    update_resp = await client.put(
        f"/roles/{viewer['id']}",
        json={"name": "Hacked"},
        headers=headers,
    )
    assert update_resp.status_code == 403
    assert update_resp.json()["error"]["code"] == "PERMISSION_DENIED"
