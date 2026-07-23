import uuid

from pydantic import BaseModel


class ModelUsageResponse(BaseModel):
    model: str
    requests: int
    total_tokens: int
    total_cost_usd: float


class UsageSummaryResponse(BaseModel):
    total_requests: int
    total_tokens: int
    total_cost_usd: float
    by_model: list[ModelUsageResponse]


class ToolUsageResponse(BaseModel):
    tool_name: str
    total_calls: int
    success_count: int
    error_count: int
    avg_duration_ms: float


class TM1ConnectionStatusResponse(BaseModel):
    connection_id: uuid.UUID
    name: str
    state: str
    failure_count: int
