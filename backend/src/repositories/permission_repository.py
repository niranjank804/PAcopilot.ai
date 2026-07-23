from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.permission import Permission


class PermissionRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        permission_id,
    ) -> Permission | None:

        result = await db.execute(
            select(Permission).where(Permission.id == permission_id)
        )

        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        db: AsyncSession,
        code: str,
    ) -> Permission | None:

        result = await db.execute(
            select(Permission).where(Permission.code == code)
        )

        return result.scalar_one_or_none()

    async def list_all(
        self,
        db: AsyncSession,
    ) -> list[Permission]:

        result = await db.execute(
            select(Permission).order_by(Permission.code)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        permission: Permission,
    ) -> Permission:

        db.add(permission)

        await db.flush()

        await db.refresh(permission)

        return permission

    async def delete(
        self,
        db: AsyncSession,
        permission: Permission,
    ) -> None:

        await db.delete(permission)
        await db.flush()


permission_repository = PermissionRepository()
