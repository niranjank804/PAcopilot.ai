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


def require_any_permission(*codes: str):
    """Pass with any one of `codes`; the error names the first (the usual
    grant), so a refusal reads the same as before for most callers."""

    async def checker(
        current_user: UserResponse = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> UserResponse:

        for code in codes:
            if await auth_repository.user_has_permission(db, current_user.id, code):
                return current_user

        raise PermissionDeniedException(f"Missing permission: {codes[0]}")

    return checker
