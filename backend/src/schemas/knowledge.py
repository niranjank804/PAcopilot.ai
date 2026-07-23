import datetime
import uuid

from pydantic import BaseModel, ConfigDict

from src.schemas.ai import UsageResponse


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    processing_status: str
    error_message: str | None
    created_at: datetime.datetime


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResultItem(BaseModel):
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    score: float


class AskRequest(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    # Optional specialist persona — when set, the answer is grounded in
    # BOTH the retrieved document context and live TM1 tool access, not
    # documents alone.
    agent: str | None = None


class CitationResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    score: float


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    model: str
    usage: UsageResponse
    citations: list[CitationResponse]


class ExplainErrorRequest(BaseModel):
    error_text: str


class ExplainErrorResponse(BaseModel):
    error_type: str
    severity: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    model: str
    usage: UsageResponse
    citations: list[CitationResponse]
