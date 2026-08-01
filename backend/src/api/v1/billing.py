from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_user
from src.billing import get_plan, list_plans, monthly_token_limit_for
from src.core.config import settings
from src.database.session import get_db
from src.repositories.ai_usage_repository import ai_usage_repository
from src.repositories.organization_repository import organization_repository
from src.schemas.auth import UserResponse
from src.schemas.billing import PlanResponse, SubscriptionResponse
from src.schemas.response import ApiResponse

router = APIRouter(
    prefix="/billing",
    tags=["Billing"],
)


@router.get(
    "/plans",
    response_model=ApiResponse[list[PlanResponse]],
)
async def list_available_plans():
    """The plan catalog. Unauthenticated: the pricing page renders from this,
    so the published entitlements and the enforced ones cannot drift."""

    return ApiResponse(
        success=True,
        data=[PlanResponse(**plan.as_dict()) for plan in list_plans()],
    )


@router.get(
    "/subscription",
    response_model=ApiResponse[SubscriptionResponse],
)
async def get_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """The caller's organization: its plan, and usage against it this month.

    Deliberately available to every authenticated user rather than admins
    only — a developer who is about to be cut off by a quota should be able
    to see that coming.
    """

    organization = await organization_repository.get_by_id(
        db, current_user.organization_id
    )

    plan = get_plan(organization.plan if organization else None)

    limit = monthly_token_limit_for(
        organization.plan if organization else None,
        deployment_limit=settings.AI_MONTHLY_TOKEN_LIMIT,
    )

    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tokens_used = await ai_usage_repository.get_total_tokens_since(
        db, current_user.organization_id, period_start
    )

    return ApiResponse(
        success=True,
        data=SubscriptionResponse(
            organization_name=organization.name if organization else "",
            plan=PlanResponse(**plan.as_dict()),
            period_start=period_start,
            tokens_used=tokens_used,
            monthly_token_limit=limit,
            tokens_remaining=(
                None if limit is None else max(0, limit - tokens_used)
            ),
            quota_exceeded=(limit is not None and tokens_used >= limit),
        ),
    )
