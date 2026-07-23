from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthenticationException, PermissionDeniedException
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.services.auth_service import auth_service
from src.services.jwt_service import jwt_service

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        payload = jwt_service.decode_token(credentials.credentials)

        if payload.get("type") != "access":
            raise AuthenticationException("Invalid token type")

        user_id = UUID(payload["sub"])

    except (JWTError, ValueError, KeyError):
        raise AuthenticationException("Invalid or expired token")

    return await auth_service.get_current_user(
        db,
        user_id,
    )


async def get_current_active_user(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:

    if not current_user.is_active:
        raise PermissionDeniedException("Inactive user")

    return current_user