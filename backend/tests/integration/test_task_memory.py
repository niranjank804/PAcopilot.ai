"""Task memory: one engineering job's working state, carried from turn to
turn so "fix it" means the thing found a moment ago — and kept apart from
engineering memory, owned, scoped and audited.

The conversational scenario runs the real API and orchestrator with a
scripted model (a fake provider): it proves what the model is GIVEN each
turn and what the system records, not how a real model would phrase things.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, ToolCall, Usage
from src.ai.tools.task_memory import SearchTaskMemoryTool, UpdateTaskMemoryTool
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_task import AITask, AITaskEvent
from src.database.models.audit_log import AuditLog
from src.database.models.engineering_memory import EngineeringMemory
from src.database.models.tm1_change import TM1Change
from src.services.task_memory_service import task_memory_service
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _user_with

FINDING = "Gross Margin is not fed at consolidations in Sales, so totals read 0."


class ScriptedProvider(AIProvider):
    """Plays one scripted reply per user turn and records what it was given."""

    def __init__(self):
        self.turns: list[dict] = []
        self.connection_id: str | None = None
        self._round = 0

    def _context(self, request: ChatRequest) -> str:
        return "\n".join(part for part in (request.system or "", request.system_context or "") if part)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        last_user = next(m.content for m in reversed(request.messages) if m.role == "user" and not m.tool_results)
        # A tool round ends with the tool results, sent as a user message.
        tool_round = bool(request.messages[-1].tool_results)
        if not tool_round:
            self.turns.append({"message": last_user, "context": self._context(request)})
        message = self.turns[-1]["message"].lower()
        usage = Usage(input_tokens=5, output_tokens=3)

        def answer(text):
            return ChatResponse(content=text, model=request.model, stop_reason="end_turn", usage=usage)

        def call(name, args):
            return ChatResponse(content="", model=request.model, stop_reason="tool_use", usage=usage,
                                tool_calls=[ToolCall(id=f"c{len(self.turns)}", name=name, input=args)])

        if message.startswith("investigate"):
            if not tool_round:
                return call("update_task_memory", {"finding": FINDING, "title": "Sales margin totals"})
            return answer("I found that Gross Margin is not fed at the totals.")
        if message.startswith("okay, fix it"):
            if not tool_round:
                return call("propose_rule_update", {
                    "connection_id": self.connection_id, "cube_name": "Sales",
                    "rules": "['Gross Margin'] = N: ['Revenue'] - ['COGS'];\nFEEDERS;\n['Revenue'] => ['Gross Margin'];",
                })
            return answer("I have prepared the feeder fix for review. I have not executed it.")
        return answer("Here is what I know.")

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def scripted():
    original = PROVIDERS.get("anthropic")
    provider = ScriptedProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


async def _say(client, headers, message, conversation_id=None, **extra):
    resp = await client.post("/ai/chat", json={
        "message": message, "agent": "developer", "conversation_id": conversation_id, **extra,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _tasks(db_session, conversation_id):
    db_session.info.pop("organization_id", None)
    return list((await db_session.execute(
        select(AITask).where(AITask.conversation_id == uuid.UUID(conversation_id))
    )).scalars())


@pytest.mark.asyncio
async def test_fix_it_resolves_against_the_task_and_stays_governed(
    client, db_session, scripted, tm1_credentials_key, fake_tm1_client,
):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")

    first = await _say(client, headers, "Investigate the Sales margin totals.", connection_id=scripted.connection_id)
    conversation = first["conversation_id"]
    task_id = first["task"]["id"]
    assert first["task"]["title"] == "Sales margin totals"

    second = await _say(client, headers, "Why did it fail?", conversation, connection_id=scripted.connection_id)
    third = await _say(client, headers, "Okay, fix it.", conversation, connection_id=scripted.connection_id)
    fourth = await _say(client, headers, "Show me what you changed.", conversation,
                        connection_id=scripted.connection_id)

    # One conversation, one task, throughout.
    assert {r["conversation_id"] for r in (second, third, fourth)} == {conversation}
    assert {r["task"]["id"] for r in (second, third, fourth)} == {task_id}
    assert len(await _tasks(db_session, conversation)) == 1

    # What the model was given: turn 2 and 3 carry the finding; turn 4 the change.
    contexts = [t["context"] for t in scripted.turns]
    assert "ACTIVE TASK" in contexts[1] and FINDING in contexts[1]
    assert FINDING in contexts[2]
    assert "update_rules on Sales: draft" in contexts[3]

    # The fix is a draft, never executed: approval is still a person's.
    db_session.info.pop("organization_id", None)
    changes = list((await db_session.execute(
        select(TM1Change).where(TM1Change.connection_id == uuid.UUID(scripted.connection_id))
    )).scalars())
    assert [c.status for c in changes] == ["draft"]
    assert third["task"]["status"] == "waiting_for_approval"
    fake_tm1_client.cubes.update.assert_not_called()

    [task] = await _tasks(db_session, conversation)
    assert [a["change_id"] for a in task.state["actions"]] == [str(changes[0].id)]  # no duplicates
    assert {"type": "cubes", "name": "Sales"} in task.state["objects"]


@pytest.mark.asyncio
async def test_a_decided_change_moves_the_task_on(client, db_session, scripted, tm1_credentials_key, fake_tm1_client):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")
    first = await _say(client, headers, "Investigate the Sales totals.", connection_id=scripted.connection_id)
    third = await _say(client, headers, "Okay, fix it.", first["conversation_id"], connection_id=scripted.connection_id)
    assert third["task"]["status"] == "waiting_for_approval"

    [task] = await _tasks(db_session, first["conversation_id"])
    change_id = task.state["actions"][0]["change_id"]
    rejected = await client.post(f"/tm1/connections/{scripted.connection_id}/changes/{change_id}/reject",
                                 headers=headers)
    assert rejected.status_code == 200, rejected.text

    after = await _say(client, headers, "What did we change?", first["conversation_id"],
                       connection_id=scripted.connection_id)
    assert "rejected" in scripted.turns[-1]["context"]
    assert after["task"]["status"] == "waiting_for_user"


@pytest.mark.asyncio
async def test_new_task_keeps_the_old_one(client, db_session, scripted, tm1_credentials_key, fake_tm1_client):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")
    first = await _say(client, headers, "Investigate the Sales totals.", connection_id=scripted.connection_id)
    second = await _say(client, headers, "Check the Region dimension", first["conversation_id"],
                        connection_id=scripted.connection_id, new_task=True)
    assert second["task"]["id"] != first["task"]["id"]
    by_phrase = await _say(client, headers, "New task: Workforce load timing", first["conversation_id"],
                           connection_id=scripted.connection_id)
    assert by_phrase["task"]["title"] == "Workforce load timing"
    tasks = await _tasks(db_session, first["conversation_id"])
    assert len(tasks) == 3
    # The earlier task, and its finding, are untouched.
    original = next(t for t in tasks if str(t.id) == first["task"]["id"])
    assert original.state["findings"][0]["text"] == FINDING

    # Continuing a named task of the conversation.
    resumed = await _say(client, headers, "Back to that one", first["conversation_id"],
                         connection_id=scripted.connection_id, task_id=first["task"]["id"])
    assert resumed["task"]["id"] == first["task"]["id"]


@pytest.mark.asyncio
async def test_plain_chat_without_tools_starts_no_task(client, db_session, scripted):
    _org, admin = await create_org_admin(db_session)
    resp = await client.post("/ai/chat", json={"message": "Can you hear me?"}, headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["task"] is None


@pytest.mark.asyncio
async def test_findings_never_become_engineering_memory(client, db_session, scripted, tm1_credentials_key,
                                                        fake_tm1_client):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")
    await _say(client, headers, "Investigate the Sales totals.", connection_id=scripted.connection_id)
    db_session.info.pop("organization_id", None)
    memories = list((await db_session.execute(
        select(EngineeringMemory).where(EngineeringMemory.text.contains("Gross Margin"))
    )).scalars())
    assert memories == []


# ------------------------------------------------------------- API and access


async def _task_via_turn(client, db_session, scripted, headers, connection_id):
    scripted.connection_id = connection_id
    data = await _say(client, headers, "Investigate the Sales totals.", connection_id=connection_id)
    return data["task"]["id"], data["conversation_id"]


@pytest.mark.asyncio
async def test_the_owner_reads_searches_and_updates_their_task(client, db_session, scripted, tm1_credentials_key,
                                                               fake_tm1_client):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    admin_id = admin.id
    connection = await _connection(client, headers, "dev")
    task_id, conversation = await _task_via_turn(client, db_session, scripted, headers, connection)

    detail = await client.get(f"/ai/tasks/{task_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()["data"]
    assert body["findings"][0]["text"] == FINDING
    assert [e["kind"] for e in body["events"]][:2] == ["created", "finding"]

    db_session.info.pop("organization_id", None)
    task = await db_session.get(AITask, uuid.UUID(task_id))
    await task_memory_service.record_tool(db_session, task, admin_id, name="get_cube",
                                          arguments={"cube_name": "Sales"}, result="{}", ok=True)
    for query in ("q=margin", f"conversation_id={conversation}", f"connection_id={connection}",
                  "object_name=sales", "status=waiting_for_user", "since_days=1"):
        listed = await client.get(f"/ai/tasks?{query}", headers=headers)
        assert [t["id"] for t in listed.json()["data"]] == [task_id], query

    updated = await client.patch(f"/ai/tasks/{task_id}", json={"status": "completed", "decision": "Ship it"},
                                 headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["status"] == "completed"
    assert updated.json()["data"]["findings"][0]["text"] == FINDING  # history kept

    archived = await client.patch(f"/ai/tasks/{task_id}", json={"status": "archived"}, headers=headers)
    assert archived.json()["data"]["status"] == "archived"
    # An archived task is not continued: the next turn starts a fresh one.
    nxt = await _say(client, headers, "Look at the Region dimension", conversation, connection_id=connection)
    assert nxt["task"]["id"] != task_id

    db_session.info.pop("organization_id", None)
    actions = {a.action for a in (await db_session.execute(
        select(AuditLog).where(AuditLog.entity == "AITask", AuditLog.entity_id == uuid.UUID(task_id))
    )).scalars()}
    assert {"task_created", "task_status_changed"} <= actions


@pytest.mark.asyncio
async def test_nobody_else_reaches_a_task(client, db_session, scripted, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection = await _connection(client, headers, "dev")
    task_id, _ = await _task_via_turn(client, db_session, scripted, headers, connection)

    colleague = await _user_with(db_session, org.id, "ai.chat")
    _other_org, stranger = await create_org_admin(db_session)
    colleague_headers, stranger_headers = auth_headers(colleague), auth_headers(stranger)
    await db_session.commit()

    for who in (colleague_headers, stranger_headers):
        assert (await client.get(f"/ai/tasks/{task_id}", headers=who)).status_code == 404
        assert (await client.patch(f"/ai/tasks/{task_id}", json={"status": "archived"},
                                   headers=who)).status_code == 404
        assert (await client.get("/ai/tasks", headers=who)).json()["data"] == []
    assert (await client.get(f"/ai/tasks/{uuid.uuid4()}", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_a_task_on_a_private_connection_disappears_when_access_does(
    client, db_session, scripted, tm1_credentials_key, fake_tm1_client,
):
    org, admin = await create_org_admin(db_session)
    member = await _user_with(db_session, org.id, "ai.chat")
    member_headers = auth_headers(member)
    await db_session.commit()
    # The member's own shared connection, then the task on it.
    connection = await _connection(client, auth_headers(admin), "dev")
    task_id, _ = await _task_via_turn(client, db_session, scripted, member_headers, connection)
    assert (await client.get(f"/ai/tasks/{task_id}", headers=member_headers)).status_code == 200

    # The connection is made private to its creator (the admin): access ends.
    resp = await client.patch(f"/tm1/connections/{connection}", json={"visibility": "private"},
                              headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    db_session.info.pop("organization_id", None)
    assert (await client.get(f"/ai/tasks/{task_id}", headers=member_headers)).status_code == 404


@pytest.mark.asyncio
async def test_task_memory_tools_record_and_find(client, db_session, scripted, tm1_credentials_key, fake_tm1_client):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection = await _connection(client, headers, "dev")
    task_id, conversation = await _task_via_turn(client, db_session, scripted, headers, connection)
    db_session.info.pop("organization_id", None)

    tool = UpdateTaskMemoryTool()
    kwargs = dict(organization_id=admin.organization_id, user_id=admin.id, conversation_id=uuid.UUID(conversation))
    result = json.loads(await tool.execute(db_session, **kwargs, decision="Add the feeder", next_step="Approve it"))
    assert result["task"]["id"] == task_id
    with pytest.raises(Exception):
        await tool.execute(db_session, **kwargs, status="waiting_for_approval")  # follows drafts only

    found = json.loads(await SearchTaskMemoryTool().execute(db_session, **kwargs, query="margin"))
    assert found["tasks"][0]["findings"] == [FINDING]
    assert found["tasks"][0]["this_conversation"] is True

    # Recovery in a new conversation: an earlier task resumed with its state.
    other = AIConversation(organization_id=admin.organization_id, user_id=admin.id, title="later")
    db_session.add(other)
    await db_session.flush()
    resumed = json.loads(await tool.execute(
        db_session, organization_id=admin.organization_id, user_id=admin.id, conversation_id=other.id,
        resume_task_id=task_id,
    ))
    new = await db_session.get(AITask, uuid.UUID(resumed["task"]["id"]))
    assert new.conversation_id == other.id and new.state["findings"][0]["text"] == FINDING
    assert new.state["resumed_from"] == task_id


@pytest.mark.asyncio
async def test_updates_append_and_never_rewrite_history(db_session):
    org, admin = await create_org_admin(db_session)
    conversation = AIConversation(organization_id=org.id, user_id=admin.id, title="t")
    db_session.add(conversation)
    await db_session.flush()
    task = await task_memory_service.create(db_session, conversation, admin.id, title="T", objective=None,
                                            agent=None, connection_id=None)
    for i in range(5):
        await task_memory_service.apply_update(db_session, task, admin.id, finding=f"fact {i}")
    await task_memory_service.apply_update(db_session, task, admin.id, actor="user", title="Renamed")
    assert [f["text"] for f in task.state["findings"]] == [f"fact {i}" for i in range(5)]
    assert task.version >= 7
    events = list((await db_session.execute(select(AITaskEvent).where(AITaskEvent.task_id == task.id))).scalars())
    title_event = next(e for e in events if e.kind == "title")
    assert title_event.data == {"from": "T", "to": "Renamed"} and title_event.actor == "user"


@pytest.mark.asyncio
async def test_two_writers_at_once_both_land():
    """Two sessions (two requests) updating one task concurrently: the row
    lock serialises them, so neither finding is lost. Uses committed rows in
    the test database, removed afterwards."""

    from src.database.models.organization import Organization
    from src.database.session import AsyncSessionLocal
    from tests.fixtures.factories import create_organization, create_user

    async with AsyncSessionLocal() as setup:
        org = await create_organization(setup)
        user = await create_user(setup, org.id)
        conversation = AIConversation(organization_id=org.id, user_id=user.id, title="t")
        setup.add(conversation)
        await setup.flush()
        task = await task_memory_service.create(setup, conversation, user.id, title="T", objective=None,
                                                agent=None, connection_id=None)
        ids = (org.id, user.id, task.id)
        await setup.commit()

    async def write(text):
        async with AsyncSessionLocal() as session:
            row = await session.get(AITask, ids[2])
            await task_memory_service.apply_update(session, row, ids[1], finding=text)
            await asyncio.sleep(0.05)  # hold the lock while the other waits
            await session.commit()

    try:
        await asyncio.gather(write("from request A"), write("from request B"))
        async with AsyncSessionLocal() as check:
            row = await check.get(AITask, ids[2])
            assert sorted(f["text"] for f in row.state["findings"]) == ["from request A", "from request B"]
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.delete(await cleanup.get(Organization, ids[0]))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_the_prompt_block_stays_bounded(db_session):
    org, admin = await create_org_admin(db_session)
    conversation = AIConversation(organization_id=org.id, user_id=admin.id, title="t")
    db_session.add(conversation)
    await db_session.flush()
    task = await task_memory_service.create(db_session, conversation, admin.id, title="Big", objective="x" * 5000,
                                            agent=None, connection_id=None)
    for i in range(60):
        await task_memory_service.apply_update(db_session, task, admin.id, finding=f"finding {i} " + "y" * 900)
        await task_memory_service.record_tool(db_session, task, admin.id, name="get_process",
                                              arguments={"process_name": f"Process {i}"}, result="{}", ok=True)
    block = await task_memory_service.prompt_block(db_session, task)
    assert len(block) < 6000
    assert "finding 59" in block and "finding 40" not in block
    assert len(task.state["findings"]) == 25  # kept; full history is in the events
    events = (await db_session.execute(
        select(AITaskEvent).where(AITaskEvent.task_id == task.id, AITaskEvent.kind == "finding")
    )).scalars().all()
    assert len(events) == 60


@pytest.mark.asyncio
async def test_a_work_item_recorded_in_the_task_links_to_it(db_session):
    from src.services.work_item_service import work_item_service

    org, admin = await create_org_admin(db_session)
    conversation = AIConversation(organization_id=org.id, user_id=admin.id, title="t")
    db_session.add(conversation)
    await db_session.flush()
    task = await task_memory_service.create(db_session, conversation, admin.id, title="T", objective=None,
                                            agent=None, connection_id=None)
    item = await work_item_service.create(db_session, organization_id=org.id, user_id=admin.id,
                                          reference="PBI 77", title="Allocation")
    await task_memory_service.record_tool(
        db_session, task, admin.id, name="save_work_item", arguments={"reference": "PBI 77"},
        result=json.dumps({"saved": True, "reference": "PBI 77", "work_item_id": str(item.id)}), ok=True,
    )
    assert task.work_item_id == item.id
    block = await task_memory_service.prompt_block(db_session, task)
    assert "Work item: PBI 77" in block
    found = await task_memory_service.search(db_session, org.id, admin.id, work_item_id=item.id)
    assert [t.id for t in found] == [task.id]


@pytest.mark.asyncio
async def test_the_last_answer_is_kept_even_when_no_finding_was_recorded(
    client, db_session, scripted, tm1_credentials_key, fake_tm1_client,
):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")
    first = await _say(client, headers, "Look at the Sales cube", connection_id=scripted.connection_id)
    await _say(client, headers, "and then?", first["conversation_id"], connection_id=scripted.connection_id)
    # The model recorded no finding; its answer still carries over, labelled as an answer.
    assert "Your last answer in this task began" in scripted.turns[-1]["context"]
    assert "Here is what I know." in scripted.turns[-1]["context"]
    [task] = await _tasks(db_session, first["conversation_id"])
    assert task.state.get("findings") in (None, [])


@pytest.mark.asyncio
async def test_five_turns_keep_one_task_and_one_draft(client, db_session, scripted, tm1_credentials_key, fake_tm1_client):
    """The hands-free conversation, turn by turn, through the one endpoint
    voice and text share: investigate, ask what caused it, ask for a fix,
    ask what the fix changes (typed), ask what to check next. The model is
    scripted, so this proves what each turn was given and what was recorded,
    not how a real model phrases it."""

    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    scripted.connection_id = await _connection(client, headers, "dev")

    turns = [
        "Investigate why the Sales margin totals fail.",
        "What caused it?",
        "Okay, fix it.",
        "Explain the proposed change.",
        "What should I check next?",
    ]
    conversation = None
    results = []
    for message in turns:
        data = await _say(client, headers, message, conversation, connection_id=scripted.connection_id)
        conversation = data["conversation_id"]
        results.append(data)

    assert {r["conversation_id"] for r in results} == {conversation}
    assert len({r["task"]["id"] for r in results}) == 1
    contexts = [t["context"] for t in scripted.turns]
    assert len(contexts) == 5
    # The finding is there from the second turn on; the draft from the fourth.
    assert all(FINDING in c for c in contexts[1:])
    assert all("update_rules on Sales: draft" in c for c in contexts[3:])
    assert "update_rules" not in contexts[1]

    db_session.info.pop("organization_id", None)
    changes = list((await db_session.execute(
        select(TM1Change).where(TM1Change.connection_id == uuid.UUID(scripted.connection_id))
    )).scalars())
    assert [c.status for c in changes] == ["draft"]  # drafted once, never executed
    fake_tm1_client.cubes.update.assert_not_called()
    assert results[2]["task"]["status"] == "waiting_for_approval"
    assert results[4]["task"]["status"] == "waiting_for_approval"
