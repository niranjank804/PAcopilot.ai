from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from src.ai.exceptions import AIProviderAuthenticationError, AIProviderRateLimitError
from src.ai.providers.anthropic_provider import AnthropicProvider
from src.ai.schemas import Attachment, ChatMessage, ChatRequest, ToolCall, ToolDefinition


def _fake_response(text: str = "Hello there"):
    block = type("Block", (), {"type": "text", "text": text})()
    usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 5})()

    return type(
        "Message",
        (),
        {
            "content": [block],
            "model": "claude-opus-4-8",
            "stop_reason": "end_turn",
            "usage": usage,
        },
    )()


def _make_request() -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        model="claude-opus-4-8",
    )


def _fake_final_message(content_blocks, stop_reason="end_turn"):
    usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 5})()

    return type(
        "Message",
        (),
        {
            "content": content_blocks,
            "stop_reason": stop_reason,
            "usage": usage,
        },
    )()


class _FakeStream:
    """Mimics anthropic's MessageStream async context manager: `text_stream`
    is an async-iterable attribute, `get_final_message()` is awaited after
    the text loop, same shape `AnthropicProvider.stream_chat` consumes."""

    def __init__(self, text_chunks, final_message):
        self._final_message = final_message
        self.text_stream = self._make_text_stream(text_chunks)

    async def _make_text_stream(self, chunks):
        for chunk in chunks:
            yield chunk

    async def get_final_message(self):
        return self._final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_chat_maps_response_to_chat_response():
    provider = AnthropicProvider()
    provider._client.messages.create = AsyncMock(return_value=_fake_response())

    response = await provider.chat(_make_request())

    assert response.content == "Hello there"
    assert response.model == "claude-opus-4-8"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5


@pytest.mark.asyncio
async def test_chat_builds_image_and_text_content_blocks_for_attachments():
    provider = AnthropicProvider()
    provider._client.messages.create = AsyncMock(return_value=_fake_response())

    request = ChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="What's in this image?",
                attachments=[
                    Attachment(filename="a.png", media_type="image/png", data="ZmFrZQ=="),
                ],
            )
        ],
        model="claude-opus-4-8",
    )

    await provider.chat(request)

    sent_messages = provider._client.messages.create.call_args.kwargs["messages"]
    blocks = sent_messages[0]["content"]

    assert blocks[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "ZmFrZQ=="},
    }
    assert blocks[1] == {"type": "text", "text": "What's in this image?"}


@pytest.mark.asyncio
async def test_chat_builds_document_block_for_pdf_attachment():
    provider = AnthropicProvider()
    provider._client.messages.create = AsyncMock(return_value=_fake_response())

    request = ChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Summarize this.",
                attachments=[
                    Attachment(filename="a.pdf", media_type="application/pdf", data="ZmFrZQ=="),
                ],
            )
        ],
        model="claude-opus-4-8",
    )

    await provider.chat(request)

    sent_messages = provider._client.messages.create.call_args.kwargs["messages"]
    blocks = sent_messages[0]["content"]

    assert blocks[0]["type"] == "document"
    assert blocks[0]["source"]["media_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_chat_translates_rate_limit_error():
    provider = AnthropicProvider()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=429, request=request)

    provider._client.messages.create = AsyncMock(
        side_effect=anthropic.RateLimitError(
            "rate limited", response=response, body=None
        )
    )

    with pytest.raises(AIProviderRateLimitError):
        await provider.chat(_make_request())


@pytest.mark.asyncio
async def test_chat_translates_authentication_error():
    provider = AnthropicProvider()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=401, request=request)

    provider._client.messages.create = AsyncMock(
        side_effect=anthropic.AuthenticationError(
            "bad key", response=response, body=None
        )
    )

    with pytest.raises(AIProviderAuthenticationError):
        await provider.chat(_make_request())


@pytest.mark.asyncio
async def test_stream_chat_yields_text_deltas_and_usage():
    provider = AnthropicProvider()
    final_message = _fake_final_message(
        [type("Block", (), {"type": "text", "text": "Hello there"})()]
    )
    provider._client.messages.stream = MagicMock(
        return_value=_FakeStream(["Hello", " there"], final_message)
    )

    events = [event async for event in provider.stream_chat(_make_request())]

    text_events = [e for e in events if e.type == "text_delta"]
    assert [e.text for e in text_events] == ["Hello", " there"]

    message_stop = [e for e in events if e.type == "message_stop"][0]
    assert message_stop.usage.input_tokens == 10
    assert message_stop.stop_reason == "end_turn"
    assert message_stop.tool_calls is None


@pytest.mark.asyncio
async def test_stream_chat_surfaces_tool_calls_and_stop_reason():
    provider = AnthropicProvider()
    tool_use_block = type(
        "Block",
        (),
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "list_cubes",
            "input": {"connection_id": "abc"},
        },
    )()
    final_message = _fake_final_message([tool_use_block], stop_reason="tool_use")
    provider._client.messages.stream = MagicMock(
        return_value=_FakeStream([], final_message)
    )

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        model="claude-opus-4-8",
        tools=[
            ToolDefinition(name="list_cubes", description="List cubes.", input_schema={}),
        ],
    )

    events = [event async for event in provider.stream_chat(request)]

    message_stop = [e for e in events if e.type == "message_stop"][0]
    assert message_stop.stop_reason == "tool_use"
    assert message_stop.tool_calls == [
        ToolCall(id="call_1", name="list_cubes", input={"connection_id": "abc"}),
    ]
