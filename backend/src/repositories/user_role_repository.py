import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.user_role import UserRole


class UserRoleRepository:

    async def get_by_user_and_role(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> UserRole | None:

        result = await db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[UserRole]:

        result = await db.execute(
            select(UserRole).where(UserRole.user_id == user_id)
        )

        return list(result.scalars().all())

    async def list_by_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
    ) -> list[UserRole]:

        result = await db.execute(
            select(UserRole).where(UserRole.role_id == role_id)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        user_role: UserRole,
    ) -> UserRole:

        db.add(user_role)

        await db.flush()

        await db.refresh(user_role)

        return user_role

    async def delete(
        self,
        db: AsyncSession,
        user_role: UserRole,
    ) -> None:

        await db.delete(user_role)
        await db.flush()


user_role_repository = UserRoleRepository()
