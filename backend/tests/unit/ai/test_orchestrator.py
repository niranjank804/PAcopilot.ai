from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from src.ai.orchestrator import ai_orchestrator
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from src.database.models.ai_usage import AIUsage
from tests.fixtures.factories import create_organization, create_user


class FakeProvider(AIProvider):

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="fake reply",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="fake ")
        yield StreamEvent(type="text_delta", text="streamed reply")
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
    yield PROVIDERS["anthropic"]
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.mark.asyncio
async def test_chat_persists_conversation_message_and_usage(db_session, fake_provider):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hello",
    )

    assert result.content == "fake reply"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 3

    usage_rows = (
        (
            await db_session.execute(
                select(AIUsage).where(AIUsage.conversation_id == result.conversation_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(usage_rows) == 1
    assert usage_rows[0].total_tokens == 10
    assert usage_rows[0].message_id == result.message_id


@pytest.mark.asyncio
async def test_stream_chat_persists_full_streamed_content(db_session, fake_provider):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    text_parts = []
    done_event = None

    async for event in ai_orchestrator.stream_chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hello",
    ):
        if event.type == "text_delta":
            text_parts.append(event.text)
        else:
            done_event = event

    assert "".join(text_parts) == "fake streamed reply"
    assert done_event is not None
    assert done_event.usage.input_tokens == 7
    assert done_event.usage.output_tokens == 3

    usage_rows = (
        (
            await db_session.execute(
                select(AIUsage).where(
                    AIUsage.conversation_id == done_event.conversation_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(usage_rows) == 1
    assert usage_rows[0].message_id == done_event.message_id
