"""Sign-in history and last activity, for the platform owner's view.

Recorded at the API layer, around the existing sign-in paths, so nothing in
how tokens are issued changes. A failed attempt raises, and the request
rolls back on an exception, so a failure's row is committed before the
caller re-raises — the attempt is the evidence, the error is the answer.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.rate_limit import client_ip_of
from src.database.models.sign_in_event import SignInEvent
from src.database.models.user import User
from src.repositories.user_repository import user_repository
from src.services.jwt_service import jwt_service


def _cut(text: str | None, length: int) -> str | None:
    return text[:length] if text else None


class SignInService:

    async def record(
        self,
        db: AsyncSession,
        request: Request,
        *,
        method: str,
        success: bool,
        identifier: str | None = None,
        access_token: str | None = None,
        reason: str | None = None,
    ) -> None:
        user: User | None = None
        if access_token:
            user = await user_repository.get_by_id(db, uuid.UUID(jwt_service.decode_token(access_token)["sub"]))
        elif identifier:
            user = await (
                user_repository.get_by_email(db, identifier)
                if "@" in identifier
                else user_repository.get_by_username(db, identifier)
            )

        now = datetime.now(UTC)
        db.add(SignInEvent(
            user_id=user.id if user else None,
            organization_id=user.organization_id if user else None,
            identifier=_cut(identifier or (user.email if user else None), 255),
            method=method,
            success=success,
            reason=_cut(reason, 255),
            ip_address=_cut(client_ip_of(request), 45),
            user_agent=_cut(request.headers.get("user-agent"), 500),
        ))
        if success and user is not None:
            user.last_login_at = now
            user.last_seen_at = now
        await db.flush()

    async def seen(self, db: AsyncSession, access_token: str) -> None:
        """Mark the token's user active now (called on each refresh)."""

        user = await user_repository.get_by_id(db, uuid.UUID(jwt_service.decode_token(access_token)["sub"]))
        if user is not None:
            user.last_seen_at = datetime.now(UTC)
            await db.flush()


sign_in_service = SignInService()
