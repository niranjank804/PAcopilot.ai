from datetime import datetime

from pydantic import BaseModel


class PlanResponse(BaseModel):

    key: str
    name: str
    description: str
    # None means unlimited, for every limit below.
    monthly_token_limit: int | None
    max_users: int | None
    max_connections: int | None
    features: list[str]
    price_label: str


class SubscriptionResponse(BaseModel):

    organization_name: str
    plan: PlanResponse
    period_start: datetime
    tokens_used: int
    monthly_token_limit: int | None
    tokens_remaining: int | None
    quota_exceeded: bool
