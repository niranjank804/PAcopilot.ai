import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GatewayCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GatewayResponse(BaseModel):
    id: uuid.UUID
    name: str
    online: bool
    last_seen_at: datetime | None
    version: str | None
    hostname: str | None
    created_at: datetime
    connection_count: int


class GatewayKeyResponse(BaseModel):
    """Shown once: the key is stored only as a digest."""

    gateway: GatewayResponse
    key: str
    server_url: str


class GatewayPollRequest(BaseModel):
    version: str | None = Field(default=None, max_length=40)
    hostname: str | None = Field(default=None, max_length=255)
    # Seconds to wait for work; capped by the server.
    wait: float = Field(default=45.0, ge=1.0, le=50.0)


class GatewayAnswerPart(BaseModel):
    id: str = Field(min_length=8, max_length=64)
    index: int = Field(ge=0, le=10_000)
    parts: int = Field(ge=1, le=10_000)
    data: str = ""
    # Part 0 only: what TM1 answered, or why it could not be asked.
    status: int | None = None
    reason: str | None = None
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None
    error: str | None = Field(default=None, max_length=2000)
