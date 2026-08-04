"""The pooled DB connection must not be held across a model call.

An agent turn spends 20-40s inside the provider and touches no database
during it. Holding the connection for that whole window capped the
deployment at pool_size + max_overflow concurrent AI requests. These
tests pin the invariant: every provider call is preceded by a commit,
which is what hands the connection back to the pool.
"""

from collections.abc import AsyncIterator

import pytest

from src.ai.orchestrator import ai_orchestrator
from src.ai.providers.base import AIProvider
from src.ai.registry import PROVIDERS
from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent, Usage
from tests.fixtures.factories import create_organization, create_user


class RecordingProvider(AIProvider):
    """Appends to a shared timeline so commit/call ordering is assertable."""

    def __init__(self, timeline: list[str]):
        self._timeline = timeline

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self._timeline.append("chat")

        return ChatResponse(
            content="fake reply",
            model=request.model,
            stop_reason="end_turn",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def stream_chat(
        self, request: ChatRequest
    ) -> AsyncIterator[StreamEvent]:
        self._timeline.append("chat")

        yield StreamEvent(type="text_delta", text="fake")
        yield StreamEvent(
            type="message_stop",
            usage=Usage(input_tokens=7, output_tokens=3),
        )

    async def count_tokens(self, request: ChatRequest) -> int:
        return 7


@pytest.fixture
def timeline(monkeypatch, db_session):
    events: list[str] = []

    original = PROVIDERS.get("anthropic")
    PROVIDERS["anthropic"] = RecordingProvider(events)

    real_commit = db_session.commit

    async def recording_commit():
        events.append("commit")
        await real_commit()

    monkeypatch.setattr(db_session, "commit", recording_commit)

    yield events

    if original is not None:
        PROVIDERS["anthropic"] = original


def _assert_commit_precedes_every_call(events: list[str]) -> None:
    assert "chat" in events, "provider was never called"

    for index, event in enumerate(events):
        if event == "chat":
            assert "commit" in events[:index], (
                "a model call ran while the pooled connection was still "
                f"checked out — timeline: {events}"
            )


@pytest.mark.asyncio
async def test_chat_commits_before_calling_the_model(db_session, timeline):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    await ai_orchestrator.chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hello",
    )

    _assert_commit_precedes_every_call(timeline)


@pytest.mark.asyncio
async def test_streaming_commits_before_calling_the_model(db_session, timeline):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    async for _event in ai_orchestrator.stream_chat(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        message="hello",
    ):
        pass

    _assert_commit_precedes_every_call(timeline)
