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
    # Fraction of prompt tokens served from cache, 0.0-1.0. A persistent
    # zero means the cached prefix is being invalidated every request, not
    # that caching is off — see src/ai/providers/anthropic_provider.py.
    cache_hit_rate: float
    cache_read_tokens: int
    cache_creation_tokens: int
    by_model: list[ModelUsageResponse]


class ToolUsageResponse(BaseModel):
    tool_name: str
    total_calls: int
    success_count: int
    error_count: int
    not_found_count: int
    avg_duration_ms: float


class TM1ConnectionStatusResponse(BaseModel):
    connection_id: uuid.UUID
    name: str
    state: str
    failure_count: int
