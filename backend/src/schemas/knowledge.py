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


class PageCitationResponse(BaseModel):
    """A page the model was shown as an image.

    Distinct from CitationResponse: that one says a passage of text was
    in the prompt, this one says a picture of a page was. A UI that
    conflated them would offer to highlight a quotation that was never
    sent.
    """

    page_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int
    score: float


class VisualStatusResponse(BaseModel):
    enabled: bool
    provider: str
    available: bool
    # Shown to an administrator, so it has to name what is missing and
    # what would fix it rather than just being false.
    reason: str


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str
    model: str
    usage: UsageResponse
    citations: list[CitationResponse]
    page_citations: list[PageCitationResponse] = []


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
