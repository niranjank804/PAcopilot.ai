import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.role_permission import RolePermission


class RolePermissionRepository:

    async def get_by_role_and_permission(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        permission_id: uuid.UUID,
    ) -> RolePermission | None:

        result = await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
    ) -> list[RolePermission]:

        result = await db.execute(
            select(RolePermission).where(RolePermission.role_id == role_id)
        )

        return list(result.scalars().all())

    async def list_by_permission(
        self,
        db: AsyncSession,
        permission_id: uuid.UUID,
    ) -> list[RolePermission]:

        result = await db.execute(
            select(RolePermission).where(
                RolePermission.permission_id == permission_id
            )
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        role_permission: RolePermission,
    ) -> RolePermission:

        db.add(role_permission)

        await db.flush()

        await db.refresh(role_permission)

        return role_permission

    async def delete(
        self,
        db: AsyncSession,
        role_permission: RolePermission,
    ) -> None:

        await db.delete(role_permission)
        await db.flush()


role_permission_repository = RolePermissionRepository()
