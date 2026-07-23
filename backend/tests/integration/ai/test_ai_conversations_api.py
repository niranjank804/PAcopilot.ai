from collections.abc import AsyncIterator

import pytest

from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from src.database.models.ai_tool_execution import AIToolExecution
from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


class FakeProvider(AIProvider):

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="fake reply",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="fake reply")
        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 7


@pytest.fixture
def fake_provider():
    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = FakeProvider()
    yield
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_new_conversation_is_auto_titled_from_first_message(
    client, db_session, fake_provider,
):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "Which cubes reference the Sales dimension?"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    list_resp = await client.get("/ai/conversations", headers=auth_headers(admin))
    conversations = list_resp.json()["data"]
    match = next(c for c in conversations if c["id"] == conversation_id)

    assert match["title"] == "Which cubes reference the Sales dimension?"


@pytest.mark.asyncio
async def test_list_conversation_messages(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    messages_resp = await client.get(
        f"/ai/conversations/{conversation_id}/messages",
        headers=auth_headers(admin),
    )

    assert messages_resp.status_code == 200
    messages = messages_resp.json()["data"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello"
    assert messages[1]["content"] == "fake reply"


@pytest.mark.asyncio
async def test_list_conversation_tool_executions(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    await ai_tool_execution_repository.create(
        db_session,
        AIToolExecution(
            conversation_id=conversation_id,
            organization_id=org.id,
            user_id=admin.id,
            tool_name="list_cubes",
            arguments={"connection_id": "abc"},
            status="success",
            result_summary="3 cubes",
            duration_ms=42,
            error_message=None,
        ),
    )
    await db_session.commit()

    exec_resp = await client.get(
        f"/ai/conversations/{conversation_id}/tool-executions",
        headers=auth_headers(admin),
    )

    assert exec_resp.status_code == 200
    executions = exec_resp.json()["data"]
    assert len(executions) == 1
    assert executions[0]["tool_name"] == "list_cubes"
    assert executions[0]["arguments"] == {"connection_id": "abc"}
    assert executions[0]["duration_ms"] == 42


@pytest.mark.asyncio
async def test_rename_conversation(client, db_session, fake_provider):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    rename_resp = await client.patch(
        f"/ai/conversations/{conversation_id}",
        json={"title": "Renamed conversation"},
        headers=auth_headers(admin),
    )

    assert rename_resp.status_code == 200
    assert rename_resp.json()["data"]["title"] == "Renamed conversation"


@pytest.mark.asyncio
async def test_delete_conversation_removes_it_from_the_list(
    client, db_session, fake_provider,
):
    org, admin = await create_org_admin(db_session)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    delete_resp = await client.delete(
        f"/ai/conversations/{conversation_id}",
        headers=auth_headers(admin),
    )
    assert delete_resp.status_code == 200

    list_resp = await client.get("/ai/conversations", headers=auth_headers(admin))
    ids = [c["id"] for c in list_resp.json()["data"]]
    assert conversation_id not in ids


@pytest.mark.asyncio
async def test_conversation_endpoints_reject_another_users_conversation(
    client, db_session, fake_provider,
):
    org, admin = await create_org_admin(db_session)
    other_user = await create_user(db_session, org.id)
    await grant_system_role(db_session, other_user.id, "Viewer")

    resp = await client.post(
        "/ai/chat",
        json={"message": "hello"},
        headers=auth_headers(admin),
    )
    conversation_id = resp.json()["data"]["conversation_id"]

    messages_resp = await client.get(
        f"/ai/conversations/{conversation_id}/messages",
        headers=auth_headers(other_user),
    )

    assert messages_resp.status_code == 404


@pytest.mark.asyncio
async def test_agents_endpoint_includes_tool_names_and_safety_notes(
    client, db_session,
):
    org, admin = await create_org_admin(db_session)

    resp = await client.get("/ai/agents", headers=auth_headers(admin))

    assert resp.status_code == 200
    agents = resp.json()["data"]
    assert len(agents) == 9
    for agent in agents:
        assert isinstance(agent["tool_names"], list) or agent["tool_names"] is None
        assert isinstance(agent["safety_notes"], list)
