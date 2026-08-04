from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.revoked_token import RevokedToken


class RevokedTokenRepository:

    async def create(
        self,
        db: AsyncSession,
        revoked: RevokedToken,
    ) -> RevokedToken:

        db.add(revoked)

        await db.flush()
        await db.refresh(revoked)

        return revoked

    async def exists(self, db: AsyncSession, jti: str) -> bool:
        """On the hot path — every authenticated request. Indexed on jti,
        and selects the id rather than the row so nothing is hydrated."""

        result = await db.execute(
            select(RevokedToken.id).where(RevokedToken.jti == jti).limit(1)
        )

        return result.scalar_one_or_none() is not None

    async def delete_expired(self, db: AsyncSession, now: datetime) -> int:
        result = await db.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < now)
        )

        return result.rowcount or 0


revoked_token_repository = RevokedTokenRepository()
