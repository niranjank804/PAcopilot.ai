from collections.abc import AsyncIterator

import anthropic

from src.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderRateLimitError,
)
from src.ai.providers.base import AIProvider
from src.ai.schemas import (
    ChatRequest,
    ChatResponse,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
)
from src.core.config import settings


def _usage_from(usage) -> Usage:
    """Map provider usage, including the cache counters.

    getattr-with-default because the cache fields are absent on older SDK
    response shapes and on the fakes used in tests; a missing counter
    should read as "no cache activity", not raise.
    """

    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        cache_read_input_tokens=(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        ),
    )


_CACHE_CONTROL = {"type": "ephemeral"}

# The API allows 4 cache breakpoints per request. One is spent on the
# stable system block (which also covers the tool schemas rendered ahead
# of it), leaving three for the conversation.
_MAX_MESSAGE_BREAKPOINTS = 3

# A breakpoint only looks back 20 content blocks for an existing cache
# entry. One agent round appends an assistant message (text + N tool_use)
# and a user message (N tool_result), so a five-round loop can put 30+
# blocks between turns — far enough that a single trailing breakpoint
# would find nothing and silently miss. Rolling markers keep every
# breakpoint within reach of the one before it.
_LOOKBACK_BLOCKS = 15


class AnthropicProvider(AIProvider):

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
        )

    def _system_payload(self, request: ChatRequest):
        """System prompt as blocks, with the stable half cached.

        Render order is tools -> system -> messages, so a breakpoint on the
        stable system block caches the tool schemas with it — the largest
        single reusable span in the request.
        """

        if not request.system and not request.system_context:
            return anthropic.NOT_GIVEN

        blocks = []

        if request.system:
            blocks.append(
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": _CACHE_CONTROL,
                }
            )

        # Deliberately unmarked, and last: this is the per-request half
        # (retrieved excerpts, live connection state). Marking it would
        # write a new cache entry on every request and never read one.
        if request.system_context:
            blocks.append({"type": "text", "text": request.system_context})

        return blocks

    def _apply_message_breakpoints(self, payload: list[dict]) -> None:
        """Mark up to three trailing positions in the conversation.

        Each agent round re-sends every prior tool result at full price
        without this. Markers accrue: the newest one writes, the older
        ones are read on the next round.
        """

        # (message index, block index) for every content block, in order.
        positions: list[tuple[int, int]] = [
            (message_index, block_index)
            for message_index, message in enumerate(payload)
            for block_index in range(
                len(message["content"])
                if isinstance(message["content"], list)
                else 1
            )
        ]

        if not positions:
            return

        chosen: list[tuple[int, int]] = []
        since_last = 0

        # Walk backwards from the newest block so the most recent turn is
        # always a breakpoint, then step back in lookback-sized strides.
        for offset, position in enumerate(reversed(positions)):
            if offset == 0 or since_last >= _LOOKBACK_BLOCKS:
                chosen.append(position)
                since_last = 0

                if len(chosen) == _MAX_MESSAGE_BREAKPOINTS:
                    break

            since_last += 1

        for message_index, block_index in chosen:
            message = payload[message_index]

            # A plain string carries no place to hang cache_control, so
            # promote it to a single text block first.
            if not isinstance(message["content"], list):
                message["content"] = [
                    {"type": "text", "text": message["content"]}
                ]

            message["content"][block_index]["cache_control"] = _CACHE_CONTROL

    def _messages_payload(self, request: ChatRequest) -> list[dict]:
        payload = []

        for message in request.messages:
            if message.tool_calls:
                blocks = []

                if message.content:
                    blocks.append({"type": "text", "text": message.content})

                blocks.extend(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.input,
                    }
                    for tool_call in message.tool_calls
                )

                payload.append({"role": message.role, "content": blocks})
            elif message.tool_results:
                blocks = [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_result.tool_call_id,
                        "content": tool_result.content,
                        "is_error": tool_result.is_error,
                    }
                    for tool_result in message.tool_results
                ]

                payload.append({"role": message.role, "content": blocks})
            elif message.attachments:
                blocks = [
                    {
                        "type": "document" if a.media_type == "application/pdf" else "image",
                        "source": {
                            "type": "base64",
                            "media_type": a.media_type,
                            "data": a.data,
                        },
                    }
                    for a in message.attachments
                ]

                if message.content:
                    blocks.append({"type": "text", "text": message.content})

                payload.append({"role": message.role, "content": blocks})
            else:
                payload.append(
                    {"role": message.role, "content": message.content}
                )

        self._apply_message_breakpoints(payload)

        return payload

    def _tools_payload(
        self,
        tools: list[ToolDefinition] | None,
    ):
        if not tools:
            return anthropic.NOT_GIVEN

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]

    async def chat(
        self,
        request: ChatRequest,
    ) -> ChatResponse:

        try:
            response = await self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=self._system_payload(request),
                messages=self._messages_payload(request),
                tools=self._tools_payload(request.tools),
            )
        except anthropic.RateLimitError as exc:
            raise AIProviderRateLimitError(str(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise AIProviderAuthenticationError(str(exc)) from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AIProviderError(str(exc)) from exc

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )

        tool_calls = [
            ToolCall(id=block.id, name=block.name, input=block.input)
            for block in response.content
            if block.type == "tool_use"
        ] or None

        return ChatResponse(
            content=text,
            model=response.model,
            stop_reason=response.stop_reason,
            usage=_usage_from(response.usage),
            tool_calls=tool_calls,
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[StreamEvent]:

        try:
            async with self._client.messages.stream(
                model=request.model,
                max_tokens=request.max_tokens,
                system=self._system_payload(request),
                messages=self._messages_payload(request),
                tools=self._tools_payload(request.tools),
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamEvent(type="text_delta", text=text)

                final_message = await stream.get_final_message()

                tool_calls = [
                    ToolCall(id=block.id, name=block.name, input=block.input)
                    for block in final_message.content
                    if block.type == "tool_use"
                ] or None

                yield StreamEvent(
                    type="message_stop",
                    usage=_usage_from(final_message.usage),
                    tool_calls=tool_calls,
                    stop_reason=final_message.stop_reason,
                )
        except anthropic.RateLimitError as exc:
            raise AIProviderRateLimitError(str(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise AIProviderAuthenticationError(str(exc)) from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AIProviderError(str(exc)) from exc

    async def count_tokens(
        self,
        request: ChatRequest,
    ) -> int:

        try:
            result = await self._client.messages.count_tokens(
                model=request.model,
                system=self._system_payload(request),
                messages=self._messages_payload(request),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AIProviderError(str(exc)) from exc

        return result.input_tokens


anthropic_provider = AnthropicProvider()
