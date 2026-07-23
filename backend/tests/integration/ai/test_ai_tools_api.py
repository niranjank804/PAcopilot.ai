import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import src.tm1.crypto as crypto_module
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, ToolCall, Usage
from src.core.config import settings
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_tool_execution import AIToolExecution
from src.database.models.ai_usage import AIUsage
from src.database.models.audit_log import AuditLog
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_usage_repository import ai_usage_repository
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import auth_headers, create_org_admin


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()
    client.cubes.get_all_names.return_value = ["Sales"]

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


class ToolCallingFakeProvider(AIProvider):

    def __init__(self):
        self.call_count = 0
        self.connection_id: str | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        if self.call_count == 1:
            return ChatResponse(
                content="",
                model=request.model,
                stop_reason="tool_use",
                usage=Usage(input_tokens=5, output_tokens=2),
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="list_cubes",
                        input={"connection_id": self.connection_id},
                    ),
                ],
            )

        return ChatResponse(
            content="You have 1 cube: Sales.",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=6, output_tokens=4),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def fake_provider():
    original = PROVIDERS.get("anthropic")
    provider = ToolCallingFakeProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_chat_with_tools_executes_tool_and_returns_final_answer(
    client, db_session, tm1_credentials_key, fake_tm1_client, fake_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=headers,
    )
    connection_id = create_resp.json()["data"]["id"]
    fake_provider.connection_id = connection_id

    resp = await client.post(
        "/ai/chat",
        json={"message": "list the cubes", "enable_tools": True},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "You have 1 cube: Sales."

    conversation_id = body["conversation_id"]

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "AIConversation",
            AuditLog.action == "chat",
        )
    )
    logs = [
        log
        for log in audit_result.scalars().all()
        if str(log.entity_id) == conversation_id
    ]
    assert len(logs) == 1

    execution_result = await db_session.execute(
        select(AIToolExecution).where(
            AIToolExecution.conversation_id == conversation_id
        )
    )
    executions = execution_result.scalars().all()
    assert len(executions) == 1
    assert executions[0].tool_name == "list_cubes"
    assert executions[0].status == "success"
    assert executions[0].arguments == {"connection_id": connection_id}


class DependencyToolFakeProvider(AIProvider):

    def __init__(self):
        self.call_count = 0
        self.connection_id: str | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        if self.call_count == 1:
            return ChatResponse(
                content="",
                model=request.model,
                stop_reason="tool_use",
                usage=Usage(input_tokens=5, output_tokens=2),
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="get_dimension_dependents",
                        input={
                            "connection_id": self.connection_id,
                            "dimension_name": "Region",
                        },
                    ),
                ],
            )

        return ChatResponse(
            content="The Sales cube depends on Region.",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=6, output_tokens=4),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def dependency_fake_provider():
    original = PROVIDERS.get("anthropic")
    provider = DependencyToolFakeProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_chat_with_tools_answers_dependency_question(
    client, db_session, tm1_credentials_key, dependency_fake_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=headers,
    )
    connection_id = create_resp.json()["data"]["id"]
    dependency_fake_provider.connection_id = connection_id

    now = datetime.now(timezone.utc)
    connection_uuid = uuid.UUID(connection_id)

    cube = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection_uuid,
            organization_id=org.id,
            object_type="cube",
            name="Sales",
            extracted_at=now,
        ),
    )
    region = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection_uuid,
            organization_id=org.id,
            object_type="dimension",
            name="Region",
            extracted_at=now,
        ),
    )
    await tm1_relationship_repository.create(
        db_session,
        TM1Relationship(
            connection_id=connection_uuid,
            organization_id=org.id,
            from_object_id=cube.id,
            to_object_id=region.id,
            relationship_type="uses_dimension",
            extracted_at=now,
        ),
    )

    resp = await client.post(
        "/ai/chat",
        json={"message": "what depends on Region?", "enable_tools": True},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "The Sales cube depends on Region."

    conversation_id = body["conversation_id"]

    execution_result = await db_session.execute(
        select(AIToolExecution).where(
            AIToolExecution.conversation_id == conversation_id
        )
    )
    executions = execution_result.scalars().all()
    assert len(executions) == 1
    assert executions[0].tool_name == "get_dimension_dependents"
    assert executions[0].status == "success"


@pytest.mark.asyncio
async def test_chat_with_developer_agent_executes_tool(
    client, db_session, tm1_credentials_key, fake_tm1_client, fake_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=headers,
    )
    connection_id = create_resp.json()["data"]["id"]
    fake_provider.connection_id = connection_id

    resp = await client.post(
        "/ai/chat",
        json={"message": "list the cubes", "agent": "developer"},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["content"] == "You have 1 cube: Sales."

    execution_result = await db_session.execute(
        select(AIToolExecution).where(
            AIToolExecution.conversation_id == body["conversation_id"]
        )
    )
    executions = execution_result.scalars().all()
    assert len(executions) == 1
    assert executions[0].tool_name == "list_cubes"
    assert executions[0].status == "success"


@pytest.mark.asyncio
async def test_chat_with_unknown_agent_returns_422(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.post(
        "/ai/chat",
        json={"message": "hi", "agent": "totally-unknown-agent"},
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_ai_agents_returns_personas(client, db_session):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.get("/ai/agents", headers=headers)

    assert resp.status_code == 200
    agents = resp.json()["data"]
    names = {agent["name"] for agent in agents}
    assert names == {
        "developer",
        "performance",
        "administrator",
        "architect",
        "documentation",
        "reviewer",
        "ti",
        "analyst",
        "troubleshooter",
    }
    assert all(isinstance(agent["max_tool_rounds"], int) for agent in agents)


class StreamToolCallingFakeProvider(AIProvider):

    def __init__(self):
        self.call_count = 0
        self.connection_id: str | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.call_count += 1

        if self.call_count == 1:
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=5, output_tokens=2),
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="list_cubes",
                        input={"connection_id": self.connection_id},
                    ),
                ],
                stop_reason="tool_use",
            )
        else:
            yield StreamEvent(type="text_delta", text="You have 1 cube: Sales.")
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=6, output_tokens=4),
                stop_reason="end_turn",
            )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def stream_fake_provider():
    original = PROVIDERS.get("anthropic")
    provider = StreamToolCallingFakeProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


def _parse_sse_events(response_text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_chat_stream_with_tools_executes_tool_and_streams_final_answer(
    client, db_session, tm1_credentials_key, fake_tm1_client, stream_fake_provider
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=headers,
    )
    connection_id = create_resp.json()["data"]["id"]
    stream_fake_provider.connection_id = connection_id

    resp = await client.post(
        "/ai/chat/stream",
        json={"message": "list the cubes", "enable_tools": True},
        headers=headers,
    )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]["tool_name"] == "list_cubes"
    assert tool_call_events[0]["tool_status"] == "success"

    text_events = [e for e in events if e["type"] == "text_delta"]
    assert "".join(e["text"] for e in text_events) == "You have 1 cube: Sales."

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1

    execution_result = await db_session.execute(
        select(AIToolExecution).where(
            AIToolExecution.conversation_id == done_events[0]["conversation_id"]
        )
    )
    executions = execution_result.scalars().all()
    assert len(executions) == 1
    assert executions[0].tool_name == "list_cubes"
    assert executions[0].status == "success"


@pytest.mark.asyncio
async def test_chat_stream_with_unknown_agent_yields_error_event(
    client, db_session
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await client.post(
        "/ai/chat/stream",
        json={"message": "hi", "agent": "totally-unknown-agent"},
        headers=headers,
    )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"


@pytest.mark.asyncio
async def test_chat_stream_with_exceeded_quota_yields_error_event(
    client, db_session
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    original_limit = settings.AI_MONTHLY_TOKEN_LIMIT
    settings.AI_MONTHLY_TOKEN_LIMIT = 100

    try:
        conversation = await ai_conversation_repository.create(
            db_session,
            AIConversation(organization_id=org.id, user_id=admin.id),
        )
        await ai_usage_repository.create(
            db_session,
            AIUsage(
                conversation_id=conversation.id,
                organization_id=org.id,
                user_id=admin.id,
                provider="anthropic",
                model="claude-opus-4-8",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                estimated_cost_usd=1.0,
                latency_ms=100,
            ),
        )

        resp = await client.post(
            "/ai/chat/stream",
            json={"message": "hi"},
            headers=headers,
        )
    finally:
        settings.AI_MONTHLY_TOKEN_LIMIT = original_limit

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
