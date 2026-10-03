"""TM1 connections are private to their creator unless shared.

The bug: everyone in an organization saw — and could use — every TM1
connection in it, including the owner's on-premises servers. These tests
are the twelve scenarios the fix must hold, through the real API (and the
AI tool layer), with separate signed-in users.
"""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.ai.orchestrator import ai_orchestrator
from src.ai.schemas import ToolCall
from src.database.models.tm1_connection import TM1Connection
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import auth_headers, create_org_admin, create_organization
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _user_with


async def _conversation(db_session, org_id, user_id):
    from src.database.models.ai_conversation import AIConversation

    conversation = AIConversation(organization_id=org_id, user_id=user_id, title="B asks")
    db_session.add(conversation)
    await db_session.flush()
    return conversation.id


async def _create(client, headers, name, visibility=None):
    body = {"name": name, "address": "tm1.example.com", "port": 8010, "ssl": True,
            "username": "admin", "password": "s3cret-tm1-password"}
    if visibility:
        body["visibility"] = visibility
    resp = await client.post("/tm1/connections", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _names(client, headers):
    resp = await client.get("/tm1/connections", headers=headers)
    assert resp.status_code == 200, resp.text
    return {c["name"] for c in resp.json()["data"]}


@pytest.fixture
async def two_users(db_session):
    """User A and User B in the same organization, both able to create and
    use connections, neither an admin."""

    org, admin = await create_org_admin(db_session)
    org_id = org.id
    a = await _user_with(db_session, org_id, "tm1.deploy")
    b = await _user_with(db_session, org_id, "tm1.deploy")
    return {
        "org_id": org_id,
        "a": auth_headers(a), "a_id": a.id,
        "b": auth_headers(b), "b_id": b.id,
        "admin": auth_headers(admin),
    }


# 1 + 2 + 3 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_user_sees_their_own_connections_and_not_others(
    client, db_session, tm1_credentials_key, two_users
):
    await _create(client, two_users["a"], "User A Dev")
    assert "User A Dev" in await _names(client, two_users["a"])          # 1
    assert "User A Dev" not in await _names(client, two_users["b"])      # 2

    await _create(client, two_users["b"], "User B Dev")
    b_sees = await _names(client, two_users["b"])
    assert "User B Dev" in b_sees and "User A Dev" not in b_sees          # 3
    assert "User B Dev" not in await _names(client, two_users["a"])


# 4 - 8: direct-id attacks ----------------------------------------------------


@pytest.mark.asyncio
async def test_user_b_cannot_reach_user_a_connection_by_id(
    client, db_session, tm1_credentials_key, fake_tm1_client, two_users, monkeypatch
):
    connection = await _create(client, two_users["a"], "User A Dev")
    cid = connection["id"]
    b = two_users["b"]
    get_client = AsyncMock(return_value=fake_tm1_client)
    monkeypatch.setattr(tm1_connection_manager, "get_client", get_client)

    # 4 read
    assert (await client.get(f"/tm1/connections/{cid}", headers=b)).status_code == 404
    # 5 update
    assert (await client.patch(f"/tm1/connections/{cid}", json={"name": "mine now"}, headers=b)).status_code == 404
    # 6 delete
    assert (await client.delete(f"/tm1/connections/{cid}", headers=b)).status_code == 404
    # 7 test — refused before any credentials are decrypted or TM1 contacted
    assert (await client.post(f"/tm1/connections/{cid}/test", headers=b)).status_code == 404
    # 8 use — reading TM1, or drafting a change, through it
    assert (await client.get(f"/tm1/connections/{cid}/cubes", headers=b)).status_code == 404
    draft = await client.post(
        f"/tm1/connections/{cid}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "x"}},
        headers=b,
    )
    assert draft.status_code == 404
    get_client.assert_not_awaited()

    # The 404 is the same as for a connection that does not exist: nothing
    # about A's connection is disclosed.
    missing = await client.get("/tm1/connections/00000000-0000-0000-0000-000000000000", headers=b)
    assert missing.json()["error"] == (await client.get(f"/tm1/connections/{cid}", headers=b)).json()["error"]

    # Still there, untouched, for its owner.
    db_session.info.pop("organization_id", None)
    row = (await db_session.execute(select(TM1Connection).where(TM1Connection.name == "User A Dev"))).scalar_one()
    assert row.name == "User A Dev"


# 9 -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_ai_cannot_use_another_users_connection(
    client, db_session, tm1_credentials_key, fake_tm1_client, two_users, monkeypatch
):
    connection = await _create(client, two_users["a"], "User A Dev")
    get_client = AsyncMock(return_value=fake_tm1_client)
    monkeypatch.setattr(tm1_connection_manager, "get_client", get_client)

    # User B's conversation; the model names A's connection.
    result = await ai_orchestrator._execute_tool_call(
        db_session,
        ToolCall(id="t1", name="list_cubes", input={"connection_id": connection["id"]}),
        organization_id=two_users["org_id"],
        user_id=two_users["b_id"],
        conversation_id=await _conversation(db_session, two_users["org_id"], two_users["b_id"]),
    )

    assert result.is_error
    assert "not found" in result.content.lower()
    assert "tm1.example.com" not in result.content
    get_client.assert_not_awaited()  # no credentials loaded, no TM1 call


@pytest.mark.asyncio
async def test_the_ai_cannot_read_another_users_dependency_map(
    client, db_session, tm1_credentials_key, two_users
):
    # Tools that read the dependency map by id never load the connection;
    # the dispatcher check is what stops them.
    connection = await _create(client, two_users["a"], "User A Dev")

    result = await ai_orchestrator._execute_tool_call(
        db_session,
        ToolCall(id="t2", name="find_unused_objects", input={"connection_id": connection["id"]}),
        organization_id=two_users["org_id"],
        user_id=two_users["b_id"],
        conversation_id=await _conversation(db_session, two_users["org_id"], two_users["b_id"]),
    )

    assert result.is_error and "not found" in result.content.lower()


# 10 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_organization_cannot_see_or_reach_it_even_when_shared(
    client, db_session, tm1_credentials_key, two_users
):
    connection = await _create(client, two_users["a"], "User A Shared", visibility="organization")
    other_org = await create_organization(db_session)
    outsider = await _user_with(db_session, other_org.id, "tm1.deploy")
    outsider_headers = auth_headers(outsider)

    assert "User A Shared" not in await _names(client, outsider_headers)
    assert (await client.get(f"/tm1/connections/{connection['id']}", headers=outsider_headers)).status_code == 404


# 11 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_shared_connection_is_usable_by_the_organization(
    client, db_session, tm1_credentials_key, fake_tm1_client, two_users
):
    connection = await _create(client, two_users["a"], "Team QA")
    assert "Team QA" not in await _names(client, two_users["b"])

    shared = await client.patch(
        f"/tm1/connections/{connection['id']}", json={"visibility": "organization"}, headers=two_users["a"]
    )
    assert shared.status_code == 200 and shared.json()["data"]["visibility"] == "organization"

    assert "Team QA" in await _names(client, two_users["b"])
    assert (await client.post(f"/tm1/connections/{connection['id']}/test", headers=two_users["b"])).status_code == 200
    # Shared to use, not to take over: B cannot make it private to themselves.
    taken = await client.patch(
        f"/tm1/connections/{connection['id']}", json={"visibility": "private"}, headers=two_users["b"]
    )
    assert taken.status_code == 403


# 12 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_admin_sees_and_manages_members_connections_but_cannot_use_them(
    client, db_session, tm1_credentials_key, fake_tm1_client, two_users
):
    connection = await _create(client, two_users["a"], "User A Dev")
    admin = two_users["admin"]

    listed = (await client.get("/tm1/connections", headers=admin)).json()["data"]
    row = next(c for c in listed if c["name"] == "User A Dev")
    assert row["can_use"] is False and row["visibility"] == "private"

    renamed = await client.patch(f"/tm1/connections/{connection['id']}", json={"name": "User A Dev (old)"}, headers=admin)
    assert renamed.status_code == 200

    # Administration, not impersonation: no TM1 call with A's credentials.
    assert (await client.post(f"/tm1/connections/{connection['id']}/test", headers=admin)).status_code == 404
    assert (await client.get(f"/tm1/connections/{connection['id']}/cubes", headers=admin)).status_code == 404

    assert (await client.delete(f"/tm1/connections/{connection['id']}", headers=admin)).status_code in (200, 204)


@pytest.mark.asyncio
async def test_no_response_carries_the_tm1_password(client, db_session, tm1_credentials_key, two_users):
    await _create(client, two_users["a"], "User A Dev")

    body = json.dumps((await client.get("/tm1/connections", headers=two_users["a"])).json())

    assert "s3cret-tm1-password" not in body
    assert "password" not in json.loads(body)["data"][0]


@pytest.mark.asyncio
async def test_ownership_comes_from_the_session_not_the_request(client, db_session, tm1_credentials_key, two_users):
    resp = await client.post(
        "/tm1/connections",
        json={"name": "Spoof", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b", "created_by": str(two_users["b_id"])},
        headers=two_users["a"],
    )

    assert resp.json()["data"]["created_by"] == str(two_users["a_id"])
    assert "Spoof" not in await _names(client, two_users["b"])


@pytest.mark.asyncio
async def test_monitoring_does_not_list_another_users_private_connection(
    client, db_session, tm1_credentials_key, two_users
):
    await _create(client, two_users["a"], "User A Dev")
    watcher = await _user_with(db_session, two_users["org_id"], "monitoring.view")

    status = await client.get("/monitoring/tm1-status", headers=auth_headers(watcher))

    assert status.status_code == 200, status.text
    assert "User A Dev" not in {c["name"] for c in status.json()["data"]}
