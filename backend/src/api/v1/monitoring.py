from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.monitoring import (
    TM1ConnectionStatusResponse,
    ToolUsageResponse,
    UsageSummaryResponse,
)
from src.schemas.response import ApiResponse
from src.services.monitoring_service import monitoring_service

router = APIRouter(
    prefix="/monitoring",
    tags=["Monitoring"],
)


@router.get(
    "/usage",
    response_model=ApiResponse[UsageSummaryResponse],
)
async def get_usage_summary(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
    days: int = Query(default=30, ge=1, le=365),
):
    summary = await monitoring_service.get_usage_summary(
        db,
        current_user.organization_id,
        days,
    )

    return ApiResponse(success=True, data=UsageSummaryResponse(**summary))


@router.get(
    "/tools",
    response_model=ApiResponse[list[ToolUsageResponse]],
)
async def get_tool_summary(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
    days: int = Query(default=30, ge=1, le=365),
):
    summary = await monitoring_service.get_tool_summary(
        db,
        current_user.organization_id,
        days,
    )

    return ApiResponse(
        success=True,
        data=[ToolUsageResponse(**entry) for entry in summary],
    )


@router.get(
    "/tm1-status",
    response_model=ApiResponse[list[TM1ConnectionStatusResponse]],
)
async def get_tm1_status(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
):
    statuses = await monitoring_service.get_tm1_status(
        db,
        current_user.organization_id,
    )

    return ApiResponse(
        success=True,
        data=[TM1ConnectionStatusResponse(**entry) for entry in statuses],
    )
