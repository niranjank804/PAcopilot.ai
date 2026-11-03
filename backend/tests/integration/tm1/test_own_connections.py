"""Analysts and Planners bring their own TM1 server (tm1.connections.own):
they add a connection and manage the ones they added, and nothing more —
not someone else's connection, not a draft change to TM1."""

import pytest

from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)


def _body(name, visibility="private"):
    return {
        "name": name,
        "address": "tm1.example.com",
        "port": 8010,
        "ssl": True,
        "username": "admin",
        "password": "secret",
        "visibility": visibility,
    }


async def _analyst(db_session, org_id, role="Analyst"):
    user = await create_user(db_session, org_id)
    await grant_system_role(db_session, user.id, role)
    headers = auth_headers(user)
    await db_session.commit()
    return headers


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["Analyst", "Planner"])
async def test_an_analyst_adds_and_manages_their_own_connection(client, db_session, tm1_credentials_key,
                                                                 fake_tm1_client, role):
    org, _admin = await create_org_admin(db_session)
    analyst = await _analyst(db_session, org.id, role)

    created = await client.post("/tm1/connections", json=_body("My dev server"), headers=analyst)
    assert created.status_code == 201, created.text
    connection = created.json()["data"]["id"]

    renamed = await client.patch(f"/tm1/connections/{connection}", json={"name": "My DEV"}, headers=analyst)
    assert renamed.status_code == 200, renamed.text

    deleted = await client.delete(f"/tm1/connections/{connection}", headers=analyst)
    assert deleted.status_code in (200, 204), deleted.text


@pytest.mark.asyncio
async def test_an_analyst_cannot_change_a_connection_someone_else_added(client, db_session, tm1_credentials_key,
                                                                         fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    admin_headers = auth_headers(admin)
    analyst = await _analyst(db_session, org.id)

    shared = await client.post("/tm1/connections", json=_body("Team server", "organization"), headers=admin_headers)
    assert shared.status_code == 201, shared.text
    shared_id = shared.json()["data"]["id"]

    # The analyst can use it …
    assert (await client.get(f"/tm1/connections/{shared_id}", headers=analyst)).status_code == 200
    # … but not change, delete or re-extract it.
    for resp in (
        await client.patch(f"/tm1/connections/{shared_id}", json={"name": "mine now"}, headers=analyst),
        await client.delete(f"/tm1/connections/{shared_id}", headers=analyst),
        await client.post(f"/tm1/connections/{shared_id}/metadata/extract", headers=analyst),
    ):
        assert resp.status_code == 403, resp.text
        assert "only the connections you added" in resp.json()["error"]["message"]

    # The admin still manages it.
    assert (await client.patch(f"/tm1/connections/{shared_id}", json={"name": "Team DEV"},
                               headers=admin_headers)).status_code == 200


@pytest.mark.asyncio
async def test_an_analyst_still_cannot_draft_changes_to_tm1(client, db_session, tm1_credentials_key,
                                                             fake_tm1_client):
    org, _admin = await create_org_admin(db_session)
    analyst = await _analyst(db_session, org.id)
    connection = (await client.post("/tm1/connections", json=_body("Mine"), headers=analyst)).json()["data"]["id"]

    draft = await client.post(
        f"/tm1/connections/{connection}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['A'] = N: 2;"}},
        headers=analyst,
    )
    assert draft.status_code == 403, draft.text
    assert "tm1.write" in draft.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_viewer_cannot_add_a_connection(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, _admin = await create_org_admin(db_session)
    viewer = await _analyst(db_session, org.id, "Viewer")

    resp = await client.post("/tm1/connections", json=_body("Nope"), headers=viewer)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_an_analysts_own_connection_stays_private_dev_and_direct(client, db_session, tm1_credentials_key,
                                                                        fake_tm1_client):
    import uuid

    org, _admin = await create_org_admin(db_session)
    analyst = await _analyst(db_session, org.id)

    refused = [
        ({**_body("Q"), "environment": "qa"}, "DEV connections"),
        ({**_body("P"), "environment": "prod"}, "DEV connections"),
        (_body("Shared", "organization"), "private to you"),
        ({**_body("G"), "gateway_id": str(uuid.uuid4())}, "gateway"),
    ]
    for body, why in refused:
        resp = await client.post("/tm1/connections", json=body, headers=analyst)
        assert resp.status_code == 403, resp.text
        assert why in resp.json()["error"]["message"]

    mine = (await client.post("/tm1/connections", json=_body("Mine"), headers=analyst)).json()["data"]["id"]
    for change, why in (
        ({"environment": "prod"}, "DEV connections"),
        ({"visibility": "organization"}, "private to you"),
        ({"gateway_id": str(uuid.uuid4())}, "gateway"),
    ):
        resp = await client.patch(f"/tm1/connections/{mine}", json=change, headers=analyst)
        assert resp.status_code == 403, resp.text
        assert why in resp.json()["error"]["message"]
