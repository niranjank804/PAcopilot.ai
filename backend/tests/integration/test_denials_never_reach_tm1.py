"""A refused request never decrypts a TM1 password and never reaches TM1.

Every test here runs through the real API, permission checks and credential
path. The only substitution is at the one place a decrypted password meets
TM1py (connection_manager._connect): the spy counts decryptions and client
constructions, and the fake transport refuses any address outside the test
set, so even a mistake here could not reach a real or production server.

Each denial asserts zero decryptions and zero TM1 connections. A positive
control in each group proves the spy sees an allowed request.
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest

import src.tm1.client.connection_manager as connection_manager_module
from src.ai.orchestrator import ai_orchestrator
from src.ai.schemas import ToolCall
from src.database.models.ai_conversation import AIConversation
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.integration.tm1.test_changes_api import tm1_credentials_key  # noqa: F401 - fixture
from tests.integration.tm1.test_environments import _user_with

TEST_ADDRESSES = {"tm1.example.com"}


@pytest.fixture
def tm1_spy(monkeypatch):
    seen = {"decrypt": 0, "connect": 0, "addresses": []}
    real_decrypt = connection_manager_module.decrypt_password

    def decrypt(value):
        seen["decrypt"] += 1
        return real_decrypt(value)

    def fake_tm1_service(**kwargs):
        address = kwargs.get("address") or kwargs.get("base_url", "")
        if not any(allowed in str(address) for allowed in TEST_ADDRESSES):
            raise AssertionError(f"refused to contact a non-test TM1 address: {address}")
        seen["connect"] += 1
        seen["addresses"].append(address)
        client = MagicMock()
        cube = MagicMock()
        cube.name, cube.dimensions, cube.has_rules = "Sales", ["Region"], True
        cube.rules.text = "['A'] = N: 1;"
        client.cubes.get.return_value = cube
        client.cubes.check_rules.return_value = []
        client.cubes.get_all_names.return_value = ["Sales"]
        client.processes.exists.return_value = False
        client.processes.compile_process.return_value = []
        return client

    monkeypatch.setattr(connection_manager_module, "decrypt_password", decrypt)
    monkeypatch.setattr(connection_manager_module, "TM1Service", fake_tm1_service)
    tm1_connection_manager._clients.clear()
    yield seen
    tm1_connection_manager._clients.clear()


def _reset(seen):
    seen["decrypt"] = seen["connect"] = 0


def _untouched(seen):
    return seen["decrypt"] == 0 and seen["connect"] == 0


async def _connection(client, headers, name, *, environment="dev", visibility=None):
    body = {"name": name, "address": "tm1.example.com", "port": 8010, "ssl": True,
            "username": "admin", "password": "s3cret", "environment": environment}
    if visibility:
        body["visibility"] = visibility
    resp = await client.post("/tm1/connections", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _draft(client, headers, connection_id):
    return await client.post(
        f"/tm1/connections/{connection_id}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['A'] = N: 2;"}},
        headers=headers,
    )


@pytest.fixture
async def people(db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    a = await _user_with(db_session, org.id, "tm1.deploy")
    b = await _user_with(db_session, org.id, "tm1.deploy")
    reader = await _user_with(db_session, org.id)  # tm1.read and tm1.write only
    _, outsider = await create_org_admin(db_session)
    await db_session.commit()
    return {"org_id": org.id, "admin": auth_headers(admin), "a": auth_headers(a), "a_id": a.id,
            "b": auth_headers(b), "b_id": b.id, "reader": auth_headers(reader), "outsider": auth_headers(outsider)}


@pytest.mark.asyncio
async def test_another_members_private_connection_is_refused_without_touching_tm1(client, people, tm1_spy):
    private = await _connection(client, people["a"], "A private")
    owner_reads = await client.get(f"/tm1/connections/{private}/cubes", headers=people["a"])
    assert owner_reads.status_code == 200, owner_reads.text
    assert tm1_spy["decrypt"] == 1 and tm1_spy["connect"] == 1  # positive control
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    for who in ("b", "outsider"):
        h = people[who]
        assert (await client.get(f"/tm1/connections/{private}", headers=h)).status_code == 404
        assert (await client.get(f"/tm1/connections/{private}/cubes", headers=h)).status_code == 404
        assert (await client.post(f"/tm1/connections/{private}/test", headers=h)).status_code == 404
        assert (await client.patch(f"/tm1/connections/{private}", json={"name": "x"}, headers=h)).status_code == 404
        assert (await client.delete(f"/tm1/connections/{private}", headers=h)).status_code == 404
        assert (await _draft(client, h, private)).status_code == 404
        assert all(c["id"] != private for c in (await client.get("/tm1/connections", headers=h)).json()["data"])
    assert _untouched(tm1_spy), tm1_spy


@pytest.mark.asyncio
async def test_unsharing_takes_access_back_without_touching_tm1(client, people, tm1_spy):
    shared = await _connection(client, people["a"], "A shared", visibility="organization")
    assert (await client.get(f"/tm1/connections/{shared}/cubes", headers=people["b"])).status_code == 200
    unshared = await client.patch(f"/tm1/connections/{shared}", json={"visibility": "private"}, headers=people["a"])
    assert unshared.status_code == 200, unshared.text
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    assert (await client.get(f"/tm1/connections/{shared}/cubes", headers=people["b"])).status_code == 404
    assert _untouched(tm1_spy), tm1_spy


@pytest.mark.asyncio
async def test_missing_permissions_are_refused_before_any_credential_is_used(client, db_session, people, tm1_spy):
    dev = await _connection(client, people["admin"], "Team DEV", visibility="organization")
    qa = await _connection(client, people["admin"], "Team QA", environment="qa", visibility="organization")
    dev_draft = (await _draft(client, people["admin"], dev)).json()["data"]["id"]
    qa_draft = (await _draft(client, people["admin"], qa)).json()["data"]["id"]
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    # No tm1.deploy: cannot apply on DEV.
    assert (await client.post(f"/tm1/connections/{dev}/changes/{dev_draft}/execute",
                              json={"acknowledge_impact": True}, headers=people["reader"])).status_code == 403
    # tm1.deploy but not tm1.deploy.qa: cannot apply on QA.
    assert (await client.post(f"/tm1/connections/{qa}/changes/{qa_draft}/execute",
                              json={"acknowledge_impact": True}, headers=people["a"])).status_code == 403
    assert _untouched(tm1_spy), tm1_spy


@pytest.mark.asyncio
async def test_prod_self_approval_is_refused_before_any_credential_is_used(client, db_session, people, tm1_spy):
    approver = await create_user(db_session, people["org_id"])
    await grant_system_role(db_session, approver.id, "Organization Admin")
    approver_headers = auth_headers(approver)
    await db_session.commit()
    prod = await _connection(client, people["admin"], "Team PROD", environment="prod", visibility="organization")
    draft = (await _draft(client, people["admin"], prod)).json()["data"]["id"]
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    own = await client.post(f"/tm1/connections/{prod}/changes/{draft}/execute",
                            json={"acknowledge_impact": True}, headers=people["admin"])
    assert own.status_code == 403
    assert _untouched(tm1_spy), tm1_spy

    # A second person may: the spy now sees exactly one connection.
    other = await client.post(f"/tm1/connections/{prod}/changes/{draft}/execute",
                              json={"acknowledge_impact": True}, headers=approver_headers)
    assert other.status_code == 200, other.text
    assert tm1_spy["connect"] == 1


@pytest.mark.asyncio
async def test_a_change_runs_once_and_stale_drafts_are_refused(client, people, tm1_spy):
    dev = await _connection(client, people["admin"], "Team DEV", visibility="organization")
    first = (await _draft(client, people["admin"], dev)).json()["data"]["id"]
    second = (await client.post(
        f"/tm1/connections/{dev}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['A'] = N: 3;"}},
        headers=people["admin"],
    )).json()["data"]["id"]  # supersedes the first draft

    stale = await client.post(f"/tm1/connections/{dev}/changes/{first}/execute",
                              json={"acknowledge_impact": True}, headers=people["admin"])
    assert stale.status_code == 409

    applied = await client.post(f"/tm1/connections/{dev}/changes/{second}/execute",
                                json={"acknowledge_impact": True}, headers=people["admin"])
    assert applied.status_code == 200, applied.text
    again = await client.post(f"/tm1/connections/{dev}/changes/{second}/execute",
                              json={"acknowledge_impact": True}, headers=people["admin"])
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_the_assistant_cannot_reach_a_connection_the_user_cannot_use(client, db_session, people, tm1_spy):
    private = await _connection(client, people["a"], "A private")
    conversation = AIConversation(organization_id=people["org_id"], user_id=people["b_id"], title="probe")
    db_session.add(conversation)
    await db_session.flush()
    db_session.info.pop("organization_id", None)
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    result = await ai_orchestrator._execute_tool_call(
        db_session,
        ToolCall(id="t1", name="list_cubes", input={"connection_id": private}),
        organization_id=people["org_id"], user_id=people["b_id"], conversation_id=conversation.id,
        allowed_tools=None, agent=None,
    )

    assert "not found" in json.dumps(getattr(result, "content", str(result))).lower()
    assert _untouched(tm1_spy), tm1_spy


@pytest.mark.asyncio
async def test_a_revoked_session_is_refused(client, people, tm1_spy):
    dev = await _connection(client, people["b"], "B DEV")
    # Every session of B's, access tokens included, is revoked.
    logout = await client.post("/auth/logout-all", headers=people["b"])
    assert logout.status_code in (200, 204), logout.text
    tm1_connection_manager._clients.clear()
    _reset(tm1_spy)

    assert (await client.get(f"/tm1/connections/{dev}/cubes", headers=people["b"])).status_code == 401
    assert _untouched(tm1_spy), tm1_spy


@pytest.mark.asyncio
async def test_an_unknown_connection_id_is_refused(client, people, tm1_spy):
    _reset(tm1_spy)
    missing = uuid.uuid4()
    assert (await client.get(f"/tm1/connections/{missing}/cubes", headers=people["a"])).status_code == 404
    assert _untouched(tm1_spy)
