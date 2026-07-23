from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:

    async def get_by_token_hash(
        self,
        db: AsyncSession,
        token_hash: str,
    ) -> PasswordResetToken | None:

        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )

        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        token: PasswordResetToken,
    ) -> PasswordResetToken:

        db.add(token)

        await db.flush()

        await db.refresh(token)

        return token

    async def mark_used(
        self,
        db: AsyncSession,
        token: PasswordResetToken,
        used_at,
    ) -> PasswordResetToken:

        token.used_at = used_at

        await db.flush()

        await db.refresh(token)

        return token


password_reset_token_repository = PasswordResetTokenRepository()
