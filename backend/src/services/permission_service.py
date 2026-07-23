import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException
from src.database.models.permission import Permission
from src.database.models.role_permission import RolePermission
from src.repositories.auth_repository import auth_repository
from src.repositories.permission_repository import permission_repository
from src.repositories.role_permission_repository import (
    role_permission_repository,
)
from src.repositories.role_repository import role_repository


class PermissionService:

    async def list_permissions(
        self,
        db: AsyncSession,
    ) -> list[Permission]:

        return await permission_repository.list_all(db)

    async def get_permission(
        self,
        db: AsyncSession,
        permission_id: uuid.UUID,
    ) -> Permission:

        permission = await permission_repository.get_by_id(
            db,
            permission_id,
        )

        if not permission:
            raise NotFoundException("Permission not found.")

        return permission

    async def list_role_permissions(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
    ) -> list[Permission]:

        return await auth_repository.get_permissions_for_role(
            db,
            role_id,
        )

    async def assign_permission(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        permission_id: uuid.UUID,
    ) -> RolePermission:

        role = await role_repository.get_by_id(
            db,
            role_id,
        )

        if not role:
            raise NotFoundException("Role not found.")

        permission = await permission_repository.get_by_id(
            db,
            permission_id,
        )

        if not permission:
            raise NotFoundException("Permission not found.")

        existing = await role_permission_repository.get_by_role_and_permission(
            db,
            role_id,
            permission_id,
        )

        if existing:
            return existing

        role_permission = RolePermission(
            role_id=role_id,
            permission_id=permission_id,
        )

        return await role_permission_repository.create(
            db,
            role_permission,
        )

    async def remove_permission(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        permission_id: uuid.UUID,
    ) -> None:

        existing = await role_permission_repository.get_by_role_and_permission(
            db,
            role_id,
            permission_id,
        )

        if not existing:
            raise NotFoundException("Permission assignment not found.")

        await role_permission_repository.delete(
            db,
            existing,
        )


permission_service = PermissionService()
