from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest

from src.ai.orchestrator import ai_orchestrator
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from src.core.config import settings
from src.core.exceptions import QuotaExceededException
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_usage_repository import ai_usage_repository
from tests.fixtures.factories import create_organization, create_user


class FakeProvider(AIProvider):

    def __init__(self):
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1

        return ChatResponse(
            content="fake reply",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.call_count += 1
        yield StreamEvent(type="text_delta", text="fake reply")
        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=7, output_tokens=3),
            stop_reason="end_turn",
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.fixture
def fake_provider():
    original = PROVIDERS.get("anthropic")
    provider = FakeProvider()
    PROVIDERS["anthropic"] = provider
    yield provider
    if original is not None:
        PROVIDERS["anthropic"] = original


@pytest.fixture
def monthly_token_limit():
    def _set(limit):
        settings.AI_MONTHLY_TOKEN_LIMIT = limit

    original = settings.AI_MONTHLY_TOKEN_LIMIT
    yield _set
    settings.AI_MONTHLY_TOKEN_LIMIT = original


async def _seed_usage(db_session, organization_id, user_id, total_tokens, created_at=None):
    conversation = await ai_conversation_repository.create(
        db_session,
        AIConversation(organization_id=organization_id, user_id=user_id),
    )

    usage = await ai_usage_repository.create(
        db_session,
        AIUsage(
            conversation_id=conversation.id,
            organization_id=organization_id,
            user_id=user_id,
            provider="anthropic",
            model="claude-opus-4-8",
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - total_tokens // 2,
            total_tokens=total_tokens,
            estimated_cost_usd=0.01,
            latency_ms=100,
        ),
    )

    if created_at is not None:
        usage.created_at = created_at
        await db_session.flush()

    return usage


@pytest.mark.asyncio
async def test_chat_raises_when_quota_exceeded(
    db_session, fake_provider, monthly_token_limit
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    monthly_token_limit(100)

    await _seed_usage(db_session, org.id, user.id, 150)

    with pytest.raises(QuotaExceededException):
        await ai_orchestrator.chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
        )

    assert fake_provider.call_count == 0


@pytest.mark.asyncio
async def test_chat_proceeds_when_under_quota(
    db_session, fake_provider, monthly_token_limit
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    monthly_token_limit(1_000_000)

    await _seed_usage(db_session, org.id, user.id, 150)

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
    )

    assert result.content == "fake reply"
    assert fake_provider.call_count == 1


@pytest.mark.asyncio
async def test_quota_check_ignores_usage_before_month_start(
    db_session, fake_provider, monthly_token_limit
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    monthly_token_limit(100)

    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=1)

    await _seed_usage(db_session, org.id, user.id, 500, created_at=last_month)

    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
    )

    assert result.content == "fake reply"
    assert fake_provider.call_count == 1


@pytest.mark.asyncio
async def test_stream_chat_raises_when_quota_exceeded(
    db_session, fake_provider, monthly_token_limit
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    monthly_token_limit(100)

    await _seed_usage(db_session, org.id, user.id, 150)

    with pytest.raises(QuotaExceededException):
        async for _ in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
        ):
            pass

    assert fake_provider.call_count == 0
