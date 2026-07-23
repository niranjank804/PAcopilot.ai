import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.core.exceptions import PermissionDeniedException
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.permission import PermissionResponse, RolePermissionAssign
from src.schemas.response import ApiResponse
from src.schemas.role import RoleCreate, RoleResponse, RoleUpdate
from src.services.audit_service import audit_service
from src.services.permission_service import permission_service
from src.services.role_service import role_service

router = APIRouter(
    prefix="/roles",
    tags=["Roles"],
)


def _client_context(http_request: Request) -> tuple[str | None, str | None]:
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    return ip_address, user_agent


@router.post(
    "",
    response_model=ApiResponse[RoleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    request: RoleCreate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.write")),
):
    role = await role_service.create_role(
        db,
        current_user.organization_id,
        request.name,
        request.description,
        False,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="create",
        entity="Role",
        entity_id=role.id,
        new_values={
            "name": role.name,
            "description": role.description,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=role)


@router.get(
    "",
    response_model=ApiResponse[list[RoleResponse]],
)
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.read")),
):
    roles = await role_service.list_roles(
        db,
        current_user.organization_id,
    )

    return ApiResponse(success=True, data=roles)


@router.get(
    "/{role_id}",
    response_model=ApiResponse[RoleResponse],
)
async def get_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.read")),
):
    role = await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    return ApiResponse(success=True, data=role)


@router.put(
    "/{role_id}",
    response_model=ApiResponse[RoleResponse],
)
async def update_role(
    role_id: uuid.UUID,
    request: RoleUpdate,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.write")),
):
    old_role = await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    old_values = {
        "name": old_role.name,
        "description": old_role.description,
    }

    role = await role_service.update_role(
        db,
        role_id,
        current_user.organization_id,
        request.name,
        request.description,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="update",
        entity="Role",
        entity_id=role.id,
        old_values=old_values,
        new_values={
            "name": role.name,
            "description": role.description,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=role)


@router.delete(
    "/{role_id}",
    response_model=ApiResponse[None],
)
async def delete_role(
    role_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.write")),
):
    old_role = await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    old_values = {
        "name": old_role.name,
        "description": old_role.description,
    }

    await role_service.delete_role(
        db,
        role_id,
        current_user.organization_id,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="delete",
        entity="Role",
        entity_id=role_id,
        old_values=old_values,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=None)


@router.get(
    "/{role_id}/permissions",
    response_model=ApiResponse[list[PermissionResponse]],
)
async def list_role_permissions(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.read")),
):
    await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    permissions = await permission_service.list_role_permissions(
        db,
        role_id,
    )

    return ApiResponse(success=True, data=permissions)


@router.post(
    "/{role_id}/permissions",
    response_model=ApiResponse[None],
    status_code=status.HTTP_201_CREATED,
)
async def assign_permission(
    role_id: uuid.UUID,
    request: RolePermissionAssign,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.write")),
):
    role = await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    if role.is_system:
        raise PermissionDeniedException(
            "Permissions on system roles cannot be modified."
        )

    await permission_service.assign_permission(
        db,
        role_id,
        request.permission_id,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="assign_permission",
        entity="Role",
        entity_id=role_id,
        new_values={"permission_id": str(request.permission_id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=None)


@router.delete(
    "/{role_id}/permissions/{permission_id}",
    response_model=ApiResponse[None],
)
async def remove_permission(
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("roles.write")),
):
    role = await role_service.get_role(
        db,
        role_id,
        current_user.organization_id,
    )

    if role.is_system:
        raise PermissionDeniedException(
            "Permissions on system roles cannot be modified."
        )

    await permission_service.remove_permission(
        db,
        role_id,
        permission_id,
    )

    ip_address, user_agent = _client_context(http_request)

    await audit_service.log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="remove_permission",
        entity="Role",
        entity_id=role_id,
        old_values={"permission_id": str(permission_id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return ApiResponse(success=True, data=None)
