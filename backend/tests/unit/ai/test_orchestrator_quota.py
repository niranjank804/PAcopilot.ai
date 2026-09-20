import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.ai.orchestrator import (
    _begin_turn,
    _end_turn,
    _estimate_tokens,
    _inflight_turns,
    ai_orchestrator,
)
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from src.core.config import settings
from src.core.exceptions import QuotaExceededException
from src.database.models.ai_conversation import AIConversation
from src.database.models.ai_usage import AIUsage
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_message_repository import ai_message_repository
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


# ---------------------------------------------------------------------------
# The check-then-act gap. Usage is written when a turn ends, so two requests
# arriving together at the edge of the limit both used to pass; and a turn
# that never ended — the client closed the stream — was never written at
# all, which made the quota optional for anyone who read the answer and hung
# up before `done`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turns_in_flight_count_against_the_quota(
    db_session, fake_provider, monthly_token_limit, monkeypatch
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    monthly_token_limit(100)
    monkeypatch.setattr(settings, "AI_QUOTA_RESERVATION_TOKENS", 60)

    await _seed_usage(db_session, org.id, user.id, 50)

    # Another request for this organization is still running: 50 used plus
    # 60 assumed for it is over the line, even though nothing is written.
    _begin_turn(org.id)

    try:
        with pytest.raises(QuotaExceededException):
            await ai_orchestrator.chat(
                db_session,
                organization_id=org.id,
                user_id=user.id,
                message="hi",
            )
    finally:
        _end_turn(org.id)

    assert fake_provider.call_count == 0

    # Once it has finished, the same request is within the limit.
    result = await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hi",
    )

    assert result.content == "fake reply"
    assert _inflight_turns(org.id) == 0


class FailingProvider(AIProvider):

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError("provider down")

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        raise RuntimeError("provider down")
        yield  # pragma: no cover

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


@pytest.mark.asyncio
async def test_a_failed_turn_releases_its_reservation(db_session, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "anthropic", FailingProvider())
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    with pytest.raises(RuntimeError):
        await ai_orchestrator.chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
        )

    assert _inflight_turns(org.id) == 0


class BlockingProvider(AIProvider):
    """Streams one delta and then never finishes — a turn that only ends
    when the client goes away."""

    def __init__(self):
        self.started = asyncio.Event()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(type="text_delta", text="partial answer text")
        self.started.set()
        await asyncio.Event().wait()

    async def count_tokens(self, request: ChatRequest) -> int:
        return 0


class _KeepOpen:
    """`async with` around the test session that does not close it, so the
    orchestrator's out-of-band write lands in the transaction the test can
    see and rolls back with it."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_an_interrupted_stream_still_records_its_usage(db_session, monkeypatch):
    provider = BlockingProvider()
    monkeypatch.setitem(PROVIDERS, "anthropic", provider)
    monkeypatch.setattr(
        ai_orchestrator, "_session_factory", lambda: _KeepOpen(db_session)
    )
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    async def consume():
        async for _ in ai_orchestrator.stream_chat(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            message="hi",
        ):
            pass

    task = asyncio.create_task(consume())
    await provider.started.wait()

    # The client hangs up mid-answer.
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    result = await db_session.execute(
        select(AIUsage).where(AIUsage.organization_id == org.id)
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    # The provider reported nothing, so the round is charged an estimate
    # of the prompt and of the text that streamed before the cut.
    assert rows[0].prompt_tokens > 0
    assert rows[0].completion_tokens == _estimate_tokens("partial answer text")
    assert rows[0].total_tokens == rows[0].prompt_tokens + rows[0].completion_tokens

    # And the answer the person watched arrive is in the conversation.
    messages = await ai_message_repository.list_by_conversation(
        db_session, rows[0].conversation_id
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[-1].content == "partial answer text"
    assert rows[0].message_id == messages[-1].id

    assert _inflight_turns(org.id) == 0
