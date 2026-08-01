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
from src.services.token_revocation_service import token_revocation_service

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

    # Cleared before the self-lookup, not just set after it: User is itself
    # OrganizationScoped, so if this session previously authenticated a
    # different org's user (a fresh AsyncSession per request in production
    # never has this problem, but a session reused across multiple
    # authentications - e.g. this app's own test harness - would otherwise
    # filter this exact lookup by a stale org id and silently 404 a real
    # user).
    db.info.pop("organization_id", None)

    # Revocation is checked here rather than at the edge because a JWT is
    # otherwise self-validating: without this, "log out" only clears the
    # browser and the token stays usable until it expires.
    if await token_revocation_service.is_revoked(db, payload):
        raise AuthenticationException("Invalid or expired token")

    current_user = await auth_service.get_current_user(
        db,
        user_id,
    )

    if token_revocation_service.issued_before_cutoff(
        payload, current_user.tokens_valid_from
    ):
        # Password changed, reset completed, or logged out everywhere.
        raise AuthenticationException("Session ended. Sign in again.")

    # Stamps the session with the caller's org for tenancy.py's
    # session-level filter. Must happen here, not inside get_db() - the
    # test suite overrides get_db wholesale (see tests/conftest.py), so
    # anything in its real body would silently never run under test.
    db.info["organization_id"] = current_user.organization_id

    return current_user


async def get_current_active_user(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:

    if not current_user.is_active:
        raise PermissionDeniedException("Inactive user")

    return current_user