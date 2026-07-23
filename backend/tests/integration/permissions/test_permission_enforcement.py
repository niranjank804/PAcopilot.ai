import pytest

from tests.fixtures.factories import (
    auth_headers,
    create_organization,
    create_user,
    grant_system_role,
)


@pytest.mark.asyncio
async def test_viewer_cannot_create_role(client, db_session):
    org = await create_organization(db_session)
    viewer_user = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer_user.id, "Viewer")

    resp = await client.post(
        "/roles",
        json={"name": "Should Fail"},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_viewer_can_list_roles(client, db_session):
    org = await create_organization(db_session)
    viewer_user = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer_user.id, "Viewer")

    resp = await client.get("/roles", headers=auth_headers(viewer_user))
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_user_with_no_roles_has_no_permissions(client, db_session):
    org = await create_organization(db_session)
    bare_user = await create_user(db_session, org.id)

    resp = await client.get("/roles", headers=auth_headers(bare_user))
    assert resp.status_code == 403
