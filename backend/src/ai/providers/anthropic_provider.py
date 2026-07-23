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


class AnthropicProvider(AIProvider):

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
        )

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
                system=request.system or anthropic.NOT_GIVEN,
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
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
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
                system=request.system or anthropic.NOT_GIVEN,
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
                    usage=Usage(
                        input_tokens=final_message.usage.input_tokens,
                        output_tokens=final_message.usage.output_tokens,
                    ),
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
                system=request.system or anthropic.NOT_GIVEN,
                messages=self._messages_payload(request),
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AIProviderError(str(exc)) from exc

        return result.input_tokens


anthropic_provider = AnthropicProvider()
