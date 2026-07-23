import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentInput(BaseModel):
    filename: str
    content_type: str
    data: str  # base64, no data: URL prefix


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None
    model: str | None = None
    enable_tools: bool = False
    agent: str | None = None
    attachments: list[AttachmentInput] | None = None


class UsageResponse(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    model: str
    usage: UsageResponse


class AgentResponse(BaseModel):
    name: str
    description: str
    max_tool_rounds: int
    tool_names: list[str] | None = None
    safety_notes: list[str] | None = None


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class ToolExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tool_name: str
    arguments: dict
    status: str
    result_summary: str | None
    duration_ms: int
    error_message: str | None
    created_at: datetime


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
