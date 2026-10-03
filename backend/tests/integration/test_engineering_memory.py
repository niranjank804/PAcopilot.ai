"""Engineering memory (phase 10): vouched-for knowledge, never AI guesses.

What must hold: a person with knowledge.write vouches by writing; anyone
else's memory and every AI suggestion waits for approval; only approved
memory reaches the assistant; edits are versions, never overwrites; one
organization never sees another's.
"""

import json

import pytest

from src.ai.orchestrator import ai_orchestrator
from src.ai.tools.memory import ProposeEngineeringMemoryTool, SearchEngineeringMemoryTool
from tests.fixtures.factories import auth_headers, create_org_admin, create_organization
from tests.integration.tm1.test_environments import _user_with


async def _add(client, headers, text, **extra):
    resp = await client.post(
        "/knowledge/memory", json={"kind": "sequence", "text": text, **extra}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


@pytest.mark.asyncio
async def test_a_knowledge_admin_vouches_by_writing(client, db_session):
    org, admin = await create_org_admin(db_session)

    memory = await _add(client, auth_headers(admin), "Load Rates must run before Load Sales.",
                        object_type="process", object_name="Load Sales")

    assert memory["status"] == "approved" and memory["source"] == "human" and memory["version"] == 1


@pytest.mark.asyncio
async def test_a_member_without_knowledge_rights_only_proposes(client, db_session):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    admin_headers = auth_headers(admin)
    member = await _user_with(db_session, org_id, "knowledge.read")
    member_headers = auth_headers(member)

    memory = await _add(client, member_headers, "The FX cube is reloaded nightly.")
    assert memory["status"] == "proposed"

    # The member cannot approve their own proposal.
    assert (await client.post(f"/knowledge/memory/{memory['id']}/approve", headers=member_headers)).status_code == 403
    approved = await client.post(f"/knowledge/memory/{memory['id']}/approve", headers=admin_headers)
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "approved"


@pytest.mark.asyncio
async def test_an_ai_suggestion_is_a_proposal_and_never_reaches_the_assistant_until_approved(
    client, db_session
):
    org, admin = await create_org_admin(db_session)
    org_id, admin_id = org.id, admin.id
    admin_headers = auth_headers(admin)

    proposed = json.loads(await ProposeEngineeringMemoryTool().execute(
        db_session, organization_id=org_id, user_id=admin_id,
        kind="caution", text="Do not change the Margin rule without the controller.",
        rationale="The user said so in this conversation.",
    ))
    assert proposed["status"] == "proposed"  # even an admin's AI suggestion waits

    _, before = await ai_orchestrator._build_tool_system_prompt(db_session, org_id, None, None)
    assert "Margin rule" not in (before or "")

    await client.post(f"/knowledge/memory/{proposed['memory_id']}/approve", headers=admin_headers)
    db_session.info.pop("organization_id", None)
    _, after = await ai_orchestrator._build_tool_system_prompt(db_session, org_id, None, None)
    assert "Margin rule" in after and "ORGANIZATION KNOWLEDGE" in after


@pytest.mark.asyncio
async def test_an_edit_is_a_new_version_and_history_keeps_the_old(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    first = await _add(client, headers, "Load Rates runs at 01:00.")

    edited = await client.put(f"/knowledge/memory/{first['id']}", json={"text": "Load Rates runs at 02:00."}, headers=headers)
    assert edited.status_code == 200
    second = edited.json()["data"]
    assert second["version"] == 2 and second["supersedes"] == first["id"]

    history = (await client.get(f"/knowledge/memory/{second['id']}/history", headers=headers)).json()["data"]
    assert [(h["version"], h["status"], h["text"]) for h in history] == [
        (2, "approved", "Load Rates runs at 02:00."),
        (1, "archived", "Load Rates runs at 01:00."),
    ]


@pytest.mark.asyncio
async def test_archived_memory_leaves_the_assistant(client, db_session):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    headers = auth_headers(admin)
    memory = await _add(client, headers, "Zebra cube is deprecated.")

    await client.post(f"/knowledge/memory/{memory['id']}/archive", headers=headers)
    db_session.info.pop("organization_id", None)
    _, prompt = await ai_orchestrator._build_tool_system_prompt(db_session, org_id, None, None)

    assert "Zebra" not in (prompt or "")


@pytest.mark.asyncio
async def test_search_finds_approved_memory_only(client, db_session):
    org, admin = await create_org_admin(db_session)
    org_id, admin_id = org.id, admin.id
    headers = auth_headers(admin)
    await _add(client, headers, "Load Sales needs Load Rates first.", object_type="process", object_name="Load Sales")
    member = await _user_with(db_session, org_id, "knowledge.read")
    await _add(client, auth_headers(member), "Load Sales is slow on Mondays.")  # proposed

    db_session.info.pop("organization_id", None)
    found = json.loads(await SearchEngineeringMemoryTool().execute(
        db_session, organization_id=org_id, user_id=admin_id, query="Load Sales"
    ))

    assert [m["text"] for m in found["memories"]] == ["Load Sales needs Load Rates first."]


@pytest.mark.asyncio
async def test_another_organization_never_sees_it(client, db_session):
    org, admin = await create_org_admin(db_session)
    memory = await _add(client, auth_headers(admin), "Secret sequence.")
    other_org, other_admin = await create_org_admin(db_session)
    other_headers = auth_headers(other_admin)

    listed = (await client.get("/knowledge/memory", headers=other_headers)).json()["data"]
    assert all(m["id"] != memory["id"] for m in listed)
    assert (await client.get(f"/knowledge/memory/{memory['id']}/history", headers=other_headers)).status_code == 404


@pytest.mark.asyncio
async def test_memory_about_a_connection_needs_access_to_it(client, db_session):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    owner = await _user_with(db_session, org_id, "tm1.deploy", "knowledge.read")
    owner_headers = auth_headers(owner)
    resp = await client.post(
        "/tm1/connections",
        json={"name": "Owner Dev", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=owner_headers,
    )
    private_connection = resp.json()["data"]["id"]
    member = await _user_with(db_session, org_id, "knowledge.read")

    refused = await client.post(
        "/knowledge/memory",
        json={"kind": "note", "text": "x", "connection_id": private_connection},
        headers=auth_headers(member),
    )
    assert refused.status_code == 404
