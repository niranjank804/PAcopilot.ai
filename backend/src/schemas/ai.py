import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AttachmentInput(BaseModel):
    filename: str
    content_type: str
    # Either the bytes inline (base64, no data: URL prefix) or the key of
    # an upload the browser put in S3 first — a chat request body cannot
    # carry a 15MB PDF through a 4.5MB function limit.
    data: str | None = None
    upload_key: str | None = None

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.data) == bool(self.upload_key):
            raise ValueError("An attachment needs exactly one of data or upload_key.")

        return self


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None
    model: str | None = None
    enable_tools: bool = False
    agent: str | None = None
    attachments: list[AttachmentInput] | None = None
    # The TM1 server chosen in the chat. Its tools go there and nowhere
    # else; without it the agent is shown every connection and picks.
    connection_id: uuid.UUID | None = None
    # Task memory: continue this task (one of this conversation's), or
    # start a new one. Neither: the conversation's current task continues.
    task_id: uuid.UUID | None = None
    new_task: bool = False


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
    task: dict | None = None


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
    visibility: str = "private"
    created_at: datetime
    updated_at: datetime


class ConversationVisibilityRequest(BaseModel):
    visibility: Literal["private", "organization"]


class SharedConversationSummary(ConversationSummary):
    owner_id: uuid.UUID
    owner_name: str


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
    agent: str | None = None
    request_id: str | None = None


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
