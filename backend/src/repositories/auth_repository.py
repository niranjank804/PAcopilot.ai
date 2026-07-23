from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.permission import Permission
from src.database.models.role import Role
from src.database.models.role_permission import RolePermission
from src.database.models.user_role import UserRole


class AuthRepository:

    async def get_roles_for_user(
        self,
        db: AsyncSession,
        user_id,
    ) -> list[Role]:

        result = await db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )

        return list(result.scalars().all())

    async def user_has_role(
        self,
        db: AsyncSession,
        user_id,
        role_name: str,
    ) -> bool:

        result = await db.execute(
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.name == role_name,
            )
        )

        return result.scalar_one_or_none() is not None

    async def get_permissions_for_role(
        self,
        db: AsyncSession,
        role_id,
    ) -> list[Permission]:

        result = await db.execute(
            select(Permission)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            )
            .where(RolePermission.role_id == role_id)
        )

        return list(result.scalars().all())

    async def user_has_permission(
        self,
        db: AsyncSession,
        user_id,
        code: str,
    ) -> bool:

        result = await db.execute(
            select(Permission.id)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            )
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user_id,
                Permission.code == code,
            )
        )

        return result.scalar_one_or_none() is not None


auth_repository = AuthRepository()
