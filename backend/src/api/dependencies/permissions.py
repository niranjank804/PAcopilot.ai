from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.auth import get_current_active_user
from src.core.exceptions import PermissionDeniedException
from src.database.session import get_db
from src.repositories.auth_repository import auth_repository
from src.schemas.auth import UserResponse


def require_permission(code: str):
    async def checker(
        current_user: UserResponse = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:

        has_permission = await auth_repository.user_has_permission(
            db,
            current_user.id,
            code,
        )

        if not has_permission:
            raise PermissionDeniedException(
                f"Missing permission: {code}"
            )

        return current_user

    return checker
