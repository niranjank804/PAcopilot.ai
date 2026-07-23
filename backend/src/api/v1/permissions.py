from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.session import get_db
from src.schemas.permission import PermissionResponse
from src.schemas.response import ApiResponse
from src.services.permission_service import permission_service

router = APIRouter(
    prefix="/permissions",
    tags=["Permissions"],
)


@router.get(
    "",
    response_model=ApiResponse[list[PermissionResponse]],
)
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("roles.read")),
):
    permissions = await permission_service.list_permissions(db)

    return ApiResponse(success=True, data=permissions)
