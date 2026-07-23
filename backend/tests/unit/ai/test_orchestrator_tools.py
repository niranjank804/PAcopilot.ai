from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from src.ai.agents.base import AgentPersona
from src.ai.orchestrator import (
    MAX_TOOL_ROUNDS,
    MAX_TOOL_ROUNDS_CEILING,
    ai_orchestrator,
)
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, ToolCall, Usage
from src.ai.tools.base import Tool
from src.core.exceptions import ValidationException
from src.database.models.ai_message import AIMessage
from src.database.models.ai_tool_execution import AIToolExecution
from tests.fixtures.factories import create_organization, create_user


class FakeTool(Tool):

    name = "fake_tool"
    description = "A fake tool for orchestrator loop tests."
    input_schema = {"type": "object", "properties": {}}

    def __init__(self):
        self.calls: list[dict] = []

    async def execute(self, db, *, organization_id, user_id, **kwargs) -> str:
        self.calls.append(kwargs)
        return "fake tool result"


class AnotherFakeTool(Tool):

    name = "another_tool"
    description = "A second fake tool, used to test agent tool restriction."
    input_schema = {"type": "object", "properties": {}}

    def __init__(self):
        self.calls: list[dict] = []

    async def execute(self, db, *, organization_id, user_id, **kwargs) -> str:
        self.calls.append(kwargs)
        return "another tool result"


class ToolUseOnceProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        if self.call_count == 1:
            return ChatResponse(
                content="",
                model=request.model,
                stop_reason="tool_use",
                usage=Usage(input_tokens=5, output_tokens=2),
                tool_calls=[
                    ToolCall(id="call_1", name="fake_tool", input={"x": 1}),
                ],
            )

        return ChatResponse(
            content="final answer",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=6, output_tokens=4),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class AlwaysToolUseProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        return ChatResponse(
            content="",
            model=request.model,
            stop_reason="tool_use",
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[
                ToolCall(id=f"call_{self.call_count}", name="fake_tool", input={}),
            ],
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class CapturingProvider(AIProvider):

    def __init__(self):
        self.last_request: ChatRequest | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request

        return ChatResponse(
            content="ok",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=1, output_tokens=1),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class ToolUseDisallowedProvider(AIProvider):
    """Simulates a misbehaving model requesting a tool outside the agent's
    allowed set — the orchestrator must reject it without executing."""

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        if self.call_count == 1:
            return ChatResponse(
                content="",
                model=request.model,
                stop_reason="tool_use",
                usage=Usage(input_tokens=1, output_tokens=1),
                tool_calls=[
                    ToolCall(id="call_1", name="another_tool", input={}),
                ],
            )

        return ChatResponse(
            content="done",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=1, output_tokens=1),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if False:  # pragma: no cover
            yield StreamEvent(type="message_stop")

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def fake_tool(monkeypatch):
    tool = FakeTool()
    monkeypatch.setattr(
        "src.ai.orchestrator.get_tool",
        lambda name: tool if name == "fake_tool" else None,
    )
    monkeypatch.setattr(
        "src.ai.orchestrator.list_tools",
        lambda: [tool],
    )
    return tool


@pytest.fixture
def two_fake_tools(monkeypatch):
    tool_a = FakeTool()
    tool_b = AnotherFakeTool()
    tools_by_name = {"fake_tool": tool_a, "another_tool": tool_b}

    monkeypatch.setattr(
        "src.ai.orchestrator.get_tool",
        lambda name: tools_by_name.get(name),
    )
    monkeypatch.setattr(
        "src.ai.orchestrator.list_tools",
        lambda: [tool_a, tool_b],
    )
    return tool_a, tool_b


@pytest.fixture
def fake_agent(monkeypatch):
    persona = AgentPersona(
        name="fake_agent",
        description="A fake persona for orchestrator tests.",
        system_prompt="You are a fake agent for tests.",
        tool_names=["fake_tool"],
    )
    monkeypatch.setattr(
        "src.ai.orchestrator.get_agent",
        lambda name: persona if name == "fake_agent" else None,
    )
    return persona


@pytest.fixture
def capturing_provider():
    original = PROVIDERS.get("anthropic")
    provider = CapturingProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def tool_use_disallowed_provider():
    original = PROVIDERS.get("anthropic")
    provider = ToolUseDisallowedProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def tool_use_once_provider():
    original = PROVIDERS.get("anthropic")
    provider = ToolUseOnceProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def always_tool_use_provider():
    original = PROVIDERS.get("anthropic")
    provider = AlwaysToolUseProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_tool_loop_executes_tool_and_persists_final_answer(
    db_session, fake_tool, tool_use_once_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    provider = tool_use_once_provider

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        enable_tools=True,
    )

    assert result.content == "final answer"
    assert provider.call_count == 2
    assert fake_tool.calls == [{"x": 1}]

    executions = (
        (
            await db_session.execute(
                select(AIToolExecution).where(
                    AIToolExecution.conversation_id == result.conversation_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(executions) == 1
    assert executions[0].tool_name == "fake_tool"
    assert executions[0].status == "success"

    assistant_messages = (
        (
            await db_session.execute(
                select(AIMessage).where(
                    AIMessage.conversation_id == result.conversation_id,
                    AIMessage.role == "assistant",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == "final answer"


@pytest.mark.asyncio
async def test_tool_loop_stops_at_round_cap_without_hanging(
    db_session, fake_tool, always_tool_use_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    provider = always_tool_use_provider

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        enable_tools=True,
    )

    assert provider.call_count == MAX_TOOL_ROUNDS
    assert len(fake_tool.calls) == MAX_TOOL_ROUNDS
    assert result.content == ""


@pytest.mark.asyncio
async def test_chat_raises_for_unknown_agent(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    with pytest.raises(ValidationException):
        await ai_orchestrator.chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
            agent="totally-unknown-agent",
        )


@pytest.mark.asyncio
async def test_agent_restricts_tools_sent_to_provider(
    db_session, two_fake_tools, fake_agent, capturing_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent",
    )

    sent_tool_names = {tool.name for tool in capturing_provider.last_request.tools}
    assert sent_tool_names == {"fake_tool"}


@pytest.mark.asyncio
async def test_agent_rejects_tool_call_outside_allowed_set(
    db_session, two_fake_tools, fake_agent, tool_use_disallowed_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    _, tool_b = two_fake_tools

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent",
    )

    assert tool_b.calls == []

    executions = (
        (
            await db_session.execute(
                select(AIToolExecution).where(
                    AIToolExecution.conversation_id == result.conversation_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(executions) == 1
    assert executions[0].tool_name == "another_tool"
    assert executions[0].status == "error"


# --- streaming tool-loop tests -----------------------------------------


class StreamToolUseOnceProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.call_count += 1

        if self.call_count == 1:
            yield StreamEvent(type="text_delta", text="checking...")
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=5, output_tokens=2),
                tool_calls=[ToolCall(id="call_1", name="fake_tool", input={"x": 1})],
                stop_reason="tool_use",
            )
        else:
            yield StreamEvent(type="text_delta", text="final answer")
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=6, output_tokens=4),
                stop_reason="end_turn",
            )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class StreamAlwaysToolUseProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.call_count += 1

        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[
                ToolCall(id=f"call_{self.call_count}", name="fake_tool", input={}),
            ],
            stop_reason="tool_use",
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class StreamCapturingProvider(AIProvider):

    def __init__(self):
        self.last_request: ChatRequest | None = None

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.last_request = request

        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class StreamToolUseDisallowedProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.call_count += 1

        if self.call_count == 1:
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=1, output_tokens=1),
                tool_calls=[ToolCall(id="call_1", name="another_tool", input={})],
                stop_reason="tool_use",
            )
        else:
            yield StreamEvent(
                type="message_stop",
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def stream_tool_use_once_provider():
    original = PROVIDERS.get("anthropic")
    provider = StreamToolUseOnceProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def stream_always_tool_use_provider():
    original = PROVIDERS.get("anthropic")
    provider = StreamAlwaysToolUseProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def stream_capturing_provider():
    original = PROVIDERS.get("anthropic")
    provider = StreamCapturingProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def stream_tool_use_disallowed_provider():
    original = PROVIDERS.get("anthropic")
    provider = StreamToolUseDisallowedProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_stream_tool_loop_executes_tool_and_persists_final_answer(
    db_session, fake_tool, stream_tool_use_once_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    provider = stream_tool_use_once_provider

    events = [
        event
        async for event in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
            enable_tools=True,
        )
    ]

    assert provider.call_count == 2
    assert fake_tool.calls == [{"x": 1}]

    tool_call_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].tool_name == "fake_tool"
    assert tool_call_events[0].tool_status == "success"

    done_event = [e for e in events if e.type == "done"][0]

    executions = (
        (
            await db_session.execute(
                select(AIToolExecution).where(
                    AIToolExecution.conversation_id == done_event.conversation_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(executions) == 1
    assert executions[0].tool_name == "fake_tool"
    assert executions[0].status == "success"

    assistant_messages = (
        (
            await db_session.execute(
                select(AIMessage).where(
                    AIMessage.conversation_id == done_event.conversation_id,
                    AIMessage.role == "assistant",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == "final answer"


@pytest.mark.asyncio
async def test_stream_tool_loop_stops_at_round_cap_without_hanging(
    db_session, fake_tool, stream_always_tool_use_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    provider = stream_always_tool_use_provider

    events = [
        event
        async for event in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
            enable_tools=True,
        )
    ]

    assert provider.call_count == MAX_TOOL_ROUNDS
    assert len(fake_tool.calls) == MAX_TOOL_ROUNDS

    done_event = [e for e in events if e.type == "done"][0]
    assert done_event.conversation_id is not None


@pytest.mark.asyncio
async def test_stream_chat_raises_for_unknown_agent(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    with pytest.raises(ValidationException):
        async for _ in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
            agent="totally-unknown-agent",
        ):
            pass


@pytest.mark.asyncio
async def test_stream_agent_restricts_tools_sent_to_provider(
    db_session, two_fake_tools, fake_agent, stream_capturing_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    async for _ in ai_orchestrator.stream_chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent",
    ):
        pass

    sent_tool_names = {
        tool.name for tool in stream_capturing_provider.last_request.tools
    }
    assert sent_tool_names == {"fake_tool"}


@pytest.mark.asyncio
async def test_stream_agent_rejects_tool_call_outside_allowed_set(
    db_session, two_fake_tools, fake_agent, stream_tool_use_disallowed_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    _, tool_b = two_fake_tools

    events = [
        event
        async for event in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
            agent="fake_agent",
        )
    ]

    assert tool_b.calls == []

    tool_call_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].tool_name == "another_tool"
    assert tool_call_events[0].tool_status == "error"


# --- per-persona max_tool_rounds ----------------------------------------


@pytest.fixture
def fake_agent_low_rounds(monkeypatch):
    persona = AgentPersona(
        name="fake_agent_low_rounds",
        description="A fake persona with a small tool-round budget.",
        system_prompt="You are a fake agent for tests.",
        tool_names=["fake_tool"],
        max_tool_rounds=2,
        safety_notes=["This is a test persona; do not trust its output."],
    )
    monkeypatch.setattr(
        "src.ai.orchestrator.get_agent",
        lambda name: persona if name == "fake_agent_low_rounds" else None,
    )
    return persona


@pytest.fixture
def fake_agent_excessive_rounds(monkeypatch):
    persona = AgentPersona(
        name="fake_agent_excessive_rounds",
        description="A fake persona whose configured budget exceeds the ceiling.",
        system_prompt="You are a fake agent for tests.",
        tool_names=["fake_tool"],
        max_tool_rounds=999,
    )
    monkeypatch.setattr(
        "src.ai.orchestrator.get_agent",
        lambda name: persona if name == "fake_agent_excessive_rounds" else None,
    )
    return persona


@pytest.mark.asyncio
async def test_persona_max_tool_rounds_overrides_the_default(
    db_session, fake_tool, fake_agent_low_rounds, always_tool_use_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent_low_rounds",
    )

    assert always_tool_use_provider.call_count == 2
    assert always_tool_use_provider.call_count != MAX_TOOL_ROUNDS


@pytest.mark.asyncio
async def test_persona_max_tool_rounds_is_clamped_to_ceiling(
    db_session, fake_tool, fake_agent_excessive_rounds, always_tool_use_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent_excessive_rounds",
    )

    assert always_tool_use_provider.call_count == MAX_TOOL_ROUNDS_CEILING


@pytest.mark.asyncio
async def test_stream_persona_max_tool_rounds_overrides_the_default(
    db_session, fake_tool, fake_agent_low_rounds, stream_always_tool_use_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    async for _ in ai_orchestrator.stream_chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent_low_rounds",
    ):
        pass

    assert stream_always_tool_use_provider.call_count == 2


@pytest.mark.asyncio
async def test_agent_safety_notes_appear_in_system_prompt(
    db_session, fake_agent_low_rounds, capturing_provider
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
        agent="fake_agent_low_rounds",
    )

    system = capturing_provider.last_request.system
    assert "Safety rules:" in system
    assert "This is a test persona; do not trust its output." in system
