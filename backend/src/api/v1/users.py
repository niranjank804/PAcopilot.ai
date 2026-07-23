import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.session import get_db
from src.schemas.auth import ApproveUserRequest, UserResponse
from src.schemas.response import ApiResponse
from src.schemas.role import RoleResponse, UserRoleAssign
from src.services.audit_service import audit_service
from src.services.role_service import role_service
from src.services.user_service import user_service

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.get(
    "",
    response_model=ApiResponse[list[UserResponse]],
)
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.read")),
    registration_status: str | None = Query(
        default=None, pattern="^(pending|approved|rejected)$"
    ),
):
    users = await user_service.list_users(
        db,
        current_user.organization_id,
        registration_status,
    )

    return ApiResponse(
        success=True,
        data=[UserResponse.model_validate(u) for u in users],
    )


@router.post(
    "/{user_id}/approve",
    response_model=ApiResponse[UserResponse],
)
async def approve_user(
    user_id: uuid.UUID,
    request: ApproveUserRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    user = await user_service.approve_user(
        db,
        user_id,
        current_user.organization_id,
        request.role_id,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="approve_user",
        entity="User",
        entity_id=user_id,
        new_values={"role_id": str(request.role_id) if request.role_id else None},
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=UserResponse.model_validate(user))


@router.post(
    "/{user_id}/deactivate",
    response_model=ApiResponse[UserResponse],
)
async def deactivate_user(
    user_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    user = await user_service.set_active(
        db,
        user_id,
        current_user.organization_id,
        current_user.id,
        is_active=False,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="deactivate_user",
        entity="User",
        entity_id=user_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=UserResponse.model_validate(user))


@router.post(
    "/{user_id}/activate",
    response_model=ApiResponse[UserResponse],
)
async def activate_user(
    user_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    user = await user_service.set_active(
        db,
        user_id,
        current_user.organization_id,
        current_user.id,
        is_active=True,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="activate_user",
        entity="User",
        entity_id=user_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=UserResponse.model_validate(user))


@router.post(
    "/{user_id}/reject",
    response_model=ApiResponse[UserResponse],
)
async def reject_user(
    user_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    user = await user_service.reject_user(
        db,
        user_id,
        current_user.organization_id,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="reject_user",
        entity="User",
        entity_id=user_id,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=UserResponse.model_validate(user))


@router.post(
    "/{user_id}/roles",
    response_model=ApiResponse[RoleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def assign_role(
    user_id: uuid.UUID,
    request: UserRoleAssign,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    await role_service.assign_role(
        db,
        user_id,
        request.role_id,
        current_user.organization_id,
    )

    role = await role_service.get_role(
        db,
        request.role_id,
        current_user.organization_id,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="assign_role",
        entity="User",
        entity_id=user_id,
        new_values={"role_id": str(request.role_id)},
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=role)


@router.get(
    "/{user_id}/roles",
    response_model=ApiResponse[list[RoleResponse]],
)
async def list_user_roles(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.read")),
):
    roles = await role_service.list_roles_for_user(
        db,
        user_id,
        current_user.organization_id,
    )

    return ApiResponse(success=True, data=roles)


@router.delete(
    "/{user_id}/roles/{role_id}",
    response_model=ApiResponse[None],
)
async def remove_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("users.write")),
):
    await role_service.remove_role(
        db,
        user_id,
        role_id,
        current_user.organization_id,
    )

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="remove_role",
        entity="User",
        entity_id=user_id,
        old_values={"role_id": str(role_id)},
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

    return ApiResponse(success=True, data=None)
