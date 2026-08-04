import uuid
from typing import Literal

from pydantic import BaseModel


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict


class ToolResult(BaseModel):
    tool_call_id: str
    content: str
    is_error: bool = False


class Attachment(BaseModel):
    filename: str
    # image/jpeg, image/png, or application/pdf only — Claude reads these
    # natively (real vision/document understanding, not OCR). DOCX has no
    # native Claude content type, so its text is extracted server-side and
    # folded into the message text instead; it never reaches this model.
    media_type: Literal["image/jpeg", "image/png", "application/pdf"]
    data: str  # base64, no data: URL prefix


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    attachments: list[Attachment] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]

    # The system prompt is split by *stability*, not by meaning. `system`
    # holds what is identical across requests for a given agent (persona
    # instructions, safety rules); `system_context` holds what varies per
    # request (retrieved knowledge, live connection state).
    #
    # Callers declare stability; providers decide what to do with it. The
    # Anthropic provider places a cache breakpoint between the two, which
    # only works because the volatile half sits after the stable half —
    # a prefix match is byte-exact, so one varying token early in the
    # prompt makes everything after it uncacheable.
    system: str | None = None
    system_context: str | None = None

    model: str
    max_tokens: int = 4096
    tools: list[ToolDefinition] | None = None


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int

    # Provider-neutral cache accounting. Zero on providers without a cache,
    # so callers can always read them. Priced differently from
    # input_tokens: reads are far cheaper, writes carry a premium.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class ChatResponse(BaseModel):
    content: str
    model: str
    stop_reason: str | None
    usage: Usage
    tool_calls: list[ToolCall] | None = None


class StreamEvent(BaseModel):
    type: Literal["text_delta", "message_stop"]
    text: str | None = None
    usage: Usage | None = None
    tool_calls: list[ToolCall] | None = None
    stop_reason: str | None = None


class OrchestratedStreamEvent(BaseModel):
    type: Literal["text_delta", "tool_call", "done"]
    text: str | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    usage: Usage | None = None
    estimated_cost_usd: float | None = None
    tool_name: str | None = None
    tool_status: Literal["success", "error"] | None = None
