"""Team collaboration: shared conversations and work items.

What must hold: a conversation is private until its owner shares it, and
shared means readable, never writable, by others; a work item never widens
access — a linked conversation or change shows its detail only to people
who could open it anyway; one organization never sees another's.
"""

import json

import pytest

from src.ai.tools.work_items import GetWorkItemTool
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_message import AIMessage
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _draft, _execute, _user_with


async def _conversation(db_session, org_id, user_id, title="Why did Load Sales fail?"):
    conversation = AIConversation(organization_id=org_id, user_id=user_id, title=title)
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(AIMessage(conversation_id=conversation.id, role="user", content="Why did Load Sales fail?"))
    # Committed (to the test savepoint), so a request that fails and rolls
    # back does not take the setup with it.
    await db_session.commit()
    return conversation.id


async def _share(client, headers, conversation_id, visibility="organization"):
    return await client.put(
        f"/ai/conversations/{conversation_id}/visibility", json={"visibility": visibility}, headers=headers
    )


async def _work_item(client, headers, reference="PBI #1234", title="Workforce load fails on the new year"):
    resp = await client.post("/team/work-items", json={"reference": reference, "title": title}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


@pytest.fixture
async def team(db_session):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    a = await _user_with(db_session, org_id, "ai.chat", "tm1.deploy")
    b = await _user_with(db_session, org_id, "ai.chat", "tm1.deploy")
    await db_session.commit()
    return {"org_id": org_id, "admin": auth_headers(admin), "admin_id": admin.id,
            "a": auth_headers(a), "a_id": a.id, "b": auth_headers(b), "b_id": b.id}


@pytest.mark.asyncio
async def test_a_conversation_is_private_until_its_owner_shares_it(client, db_session, team):
    conversation = await _conversation(db_session, team["org_id"], team["a_id"])
    messages = f"/ai/conversations/{conversation}/messages"

    assert (await client.get(messages, headers=team["b"])).status_code == 404
    assert all(c["id"] != str(conversation) for c in
               (await client.get("/team/conversations", headers=team["b"])).json()["data"])

    shared = await _share(client, team["a"], conversation)
    assert shared.status_code == 200 and shared.json()["data"]["visibility"] == "organization"

    read = await client.get(messages, headers=team["b"])
    assert read.status_code == 200 and read.json()["data"][0]["content"] == "Why did Load Sales fail?"
    listed = (await client.get("/team/conversations", headers=team["b"])).json()["data"]
    assert [c["owner_name"] for c in listed if c["id"] == str(conversation)]

    # Unsharing takes it back.
    await _share(client, team["a"], conversation, "private")
    assert (await client.get(messages, headers=team["b"])).status_code == 404


@pytest.mark.asyncio
async def test_shared_is_read_only_for_everyone_but_the_owner(client, db_session, team):
    conversation = await _conversation(db_session, team["org_id"], team["a_id"])
    await _share(client, team["a"], conversation)

    assert (await _share(client, team["b"], conversation, "private")).status_code == 404
    assert (await client.patch(f"/ai/conversations/{conversation}", json={"title": "x"},
                               headers=team["b"])).status_code == 404
    assert (await client.delete(f"/ai/conversations/{conversation}", headers=team["b"])).status_code == 404
    # Still there, still shared.
    assert (await client.get(f"/ai/conversations/{conversation}/messages", headers=team["b"])).status_code == 200


@pytest.mark.asyncio
async def test_another_organization_never_sees_shared_conversations_or_work_items(client, db_session, team):
    conversation = await _conversation(db_session, team["org_id"], team["a_id"])
    await _share(client, team["a"], conversation)
    item = await _work_item(client, team["a"])
    _, outsider = await create_org_admin(db_session)
    outsider_headers = auth_headers(outsider)
    await db_session.commit()

    assert (await client.get(f"/ai/conversations/{conversation}/messages", headers=outsider_headers)).status_code == 404
    assert (await client.get("/team/conversations", headers=outsider_headers)).json()["data"] == []
    assert (await client.get(f"/team/work-items/{item}", headers=outsider_headers)).status_code == 404
    assert (await client.get("/team/work-items", headers=outsider_headers)).json()["data"] == []


@pytest.mark.asyncio
async def test_a_reference_is_unique_in_the_organization(client, db_session, team):
    await _work_item(client, team["a"], "PBI #1234")
    again = await client.post("/team/work-items", json={"reference": "pbi #1234", "title": "x"}, headers=team["b"])
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_status_and_root_cause_are_on_the_timeline_with_who(client, db_session, team):
    item = await _work_item(client, team["a"])

    resp = await client.patch(
        f"/team/work-items/{item}",
        json={"status": "in_progress", "root_cause": "Year dimension has no 2027 element."},
        headers=team["b"],
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["data"]

    titles = [e["title"] for e in detail["events"]]
    assert titles[0] == "PBI #1234 opened"
    assert "Status set to in progress" in titles and "Root cause recorded" in titles
    root = next(e for e in detail["events"] if e["kind"] == "root_cause")
    assert root["detail"] == "Year dimension has no 2027 element." and root["actor"]
    assert {p["key"]: p["done"] for p in detail["progress"]}["root_cause"] is True


@pytest.mark.asyncio
async def test_only_a_shared_conversation_can_be_linked(client, db_session, team):
    item = await _work_item(client, team["a"])
    conversation = await _conversation(db_session, team["org_id"], team["a_id"])
    link = {"kind": "conversation", "target_id": str(conversation)}

    private = await client.post(f"/team/work-items/{item}/links", json=link, headers=team["a"])
    assert private.status_code == 409 and "Share" in private.json()["error"]["message"]

    # Someone else cannot link A's private conversation either — nor learn it exists.
    assert (await client.post(f"/team/work-items/{item}/links", json=link, headers=team["b"])).status_code == 404

    await _share(client, team["a"], conversation)
    linked = await client.post(f"/team/work-items/{item}/links", json=link, headers=team["a"])
    assert linked.status_code == 201, linked.text
    detail = linked.json()["data"]
    assert detail["links"][0]["available"] and detail["links"][0]["messages"] == 1
    assert {p["key"]: p["done"] for p in detail["progress"]}["investigation"] is True

    # Unshared later: B sees a placeholder, not the conversation.
    await _share(client, team["a"], conversation, "private")
    seen_by_b = (await client.get(f"/team/work-items/{item}", headers=team["b"])).json()["data"]
    assert seen_by_b["links"][0]["available"] is False
    assert "Load Sales" not in json.dumps(seen_by_b)


@pytest.mark.asyncio
async def test_a_linked_change_tells_the_story_from_proposal_to_applied(
    client, db_session, tm1_credentials_key, fake_tm1_client, team
):
    connection = await _connection(client, team["admin"], "dev")
    change = await _draft(client, team["admin"], connection)
    item = await _work_item(client, team["a"])

    linked = await client.post(
        f"/team/work-items/{item}/links", json={"kind": "change", "target_id": change}, headers=team["a"]
    )
    assert linked.status_code == 201, linked.text
    progress = {p["key"]: p["done"] for p in linked.json()["data"]["progress"]}
    assert progress["fix"] and not progress["approval"]

    assert (await _execute(client, team["admin"], connection, change)).status_code == 200
    detail = (await client.get(f"/team/work-items/{item}", headers=team["b"])).json()["data"]

    titles = " | ".join(e["title"] for e in detail["events"])
    assert "Fix proposed" in titles and "Approved" in titles and "Applied" in titles
    progress = {p["key"]: p["done"] for p in detail["progress"]}
    assert progress["approval"] and progress["deployment"] and not progress["verification"]
    assert detail["links"][0]["environment"] == "dev" and detail["links"][0]["status"] == "executed"


@pytest.mark.asyncio
async def test_a_change_on_a_private_connection_stays_private_on_the_work_item(
    client, db_session, tm1_credentials_key, fake_tm1_client, team
):
    resp = await client.post(
        "/tm1/connections",
        json={"name": "A private", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=team["a"],
    )
    private_connection = resp.json()["data"]["id"]
    change = await _draft(client, team["a"], private_connection)
    item = await _work_item(client, team["a"])

    # B cannot link it, and is told only "not found".
    refused = await client.post(
        f"/team/work-items/{item}/links", json={"kind": "change", "target_id": change}, headers=team["b"]
    )
    assert refused.status_code == 404

    await client.post(f"/team/work-items/{item}/links", json={"kind": "change", "target_id": change}, headers=team["a"])
    seen_by_b = (await client.get(f"/team/work-items/{item}", headers=team["b"])).json()["data"]
    assert seen_by_b["links"][0]["available"] is False
    assert "Sales" not in json.dumps(seen_by_b) and "A private" not in json.dumps(seen_by_b)

    # Nor in B's team activity.
    activity = (await client.get("/team/activity", headers=team["b"])).json()["data"]
    assert all(c["id"] != change for c in activity["changes"])
    assert any(c["id"] == change for c in (await client.get("/team/activity", headers=team["a"])).json()["data"]["changes"])


@pytest.mark.asyncio
async def test_the_assistant_reads_a_work_item_by_reference(client, db_session, team):
    item = await _work_item(client, team["a"])
    await client.patch(f"/team/work-items/{item}", json={"root_cause": "Missing 2027 element."}, headers=team["a"])
    db_session.info.pop("organization_id", None)

    found = json.loads(await GetWorkItemTool().execute(
        db_session, organization_id=team["org_id"], user_id=team["b_id"], reference="pbi #1234"
    ))
    assert found["found"] and found["root_cause"] == "Missing 2027 element."
    assert found["progress"]["Root cause"] is True

    missing = json.loads(await GetWorkItemTool().execute(
        db_session, organization_id=team["org_id"], user_id=team["b_id"], reference="PBI"
    ))
    assert missing["found"] is False and missing["similar"][0]["reference"] == "PBI #1234"
