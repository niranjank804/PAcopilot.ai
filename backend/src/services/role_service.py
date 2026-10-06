import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    PermissionDeniedException,
)
from src.database.models.role import Role
from src.database.models.user_role import UserRole
from src.repositories.auth_repository import auth_repository
from src.repositories.role_repository import role_repository
from src.repositories.user_repository import user_repository
from src.repositories.user_role_repository import user_role_repository


# The platform owner's role. A system role (no organization), so a role an
# organization creates under the same name is not it.
SUPER_ADMIN_ROLE = "Super Admin"


class RoleService:

    async def is_super_admin(self, db: AsyncSession, user_id: uuid.UUID) -> bool:
        result = await db.execute(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                Role.name == SUPER_ADMIN_ROLE,
                Role.is_system.is_(True),
                Role.organization_id.is_(None),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Role:

        role = await role_repository.get_by_id(
            db,
            role_id,
        )

        if not role or role.organization_id not in (organization_id, None):
            raise NotFoundException("Role not found.")

        return role

    async def update_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        organization_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> Role:

        role = await self.get_role(db, role_id, organization_id)

        if role.is_system:
            raise PermissionDeniedException(
                "System roles cannot be modified."
            )

        if name is not None:
            role.name = name

        if description is not None:
            role.description = description

        return await role_repository.update(
            db,
            role,
        )

    async def delete_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        role = await self.get_role(db, role_id, organization_id)

        if role.is_system:
            raise PermissionDeniedException(
                "System roles cannot be deleted."
            )

        await role_repository.delete(
            db,
            role,
        )

    async def list_roles_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
    ) -> list[Role]:

        user = await user_repository.get_by_id(
            db,
            user_id,
        )

        if not user or user.organization_id != caller_organization_id:
            raise PermissionDeniedException(
                "Cannot view roles for a user outside your organization."
            )

        return await auth_repository.get_roles_for_user(
            db,
            user_id,
        )

    async def create_role(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID | None,
        name: str,
        description: str | None = None,
        is_system: bool = False,
    ) -> Role:

        existing = await role_repository.get_by_name(
            db,
            organization_id,
            name,
        )

        if existing:
            raise ConflictException(
                f"Role '{name}' already exists."
            )

        role = Role(
            organization_id=organization_id,
            name=name,
            description=description,
            is_system=is_system,
        )

        return await role_repository.create(
            db,
            role,
        )

    async def assign_role(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
        caller_user_id: uuid.UUID | None = None,
    ) -> UserRole:

        user = await user_repository.get_by_id(
            db,
            user_id,
        )

        if not user or user.organization_id != caller_organization_id:
            raise PermissionDeniedException(
                "Cannot assign roles to a user outside your organization."
            )

        role = await role_repository.get_by_id(
            db,
            role_id,
        )

        if not role or role.organization_id not in (caller_organization_id, None):
            raise PermissionDeniedException(
                "Cannot assign a role outside your organization."
            )

        # Every sign-up administers a workspace of its own, and a workspace
        # admin may hand out system roles — so without this, anyone could
        # make themselves the platform's Super Admin.
        if (
            role.is_system
            and role.name == SUPER_ADMIN_ROLE
            and not (caller_user_id and await self.is_super_admin(db, caller_user_id))
        ):
            raise PermissionDeniedException(
                "Only a Super Admin can grant the Super Admin role."
            )

        existing = await user_role_repository.get_by_user_and_role(
            db,
            user_id,
            role_id,
        )

        if existing:
            return existing

        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
        )

        return await user_role_repository.create(
            db,
            user_role,
        )

    async def remove_role(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        caller_organization_id: uuid.UUID,
        caller_user_id: uuid.UUID | None = None,
    ) -> None:

        user = await user_repository.get_by_id(
            db,
            user_id,
        )

        if not user or user.organization_id != caller_organization_id:
            raise PermissionDeniedException(
                "Cannot remove roles from a user outside your organization."
            )

        # The mirror of assign_role's guard: a workspace admin must not be
        # able to strip the platform's Super Admin of that role either.
        role = await role_repository.get_by_id(db, role_id)
        if (
            role is not None
            and role.is_system
            and role.name == SUPER_ADMIN_ROLE
            and not (caller_user_id and await self.is_super_admin(db, caller_user_id))
        ):
            raise PermissionDeniedException(
                "Only a Super Admin can remove the Super Admin role."
            )

        existing = await user_role_repository.get_by_user_and_role(
            db,
            user_id,
            role_id,
        )

        if not existing:
            raise NotFoundException("Role assignment not found.")

        await user_role_repository.delete(
            db,
            existing,
        )

    async def list_roles(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[Role]:

        return await role_repository.list_visible_to_organization(
            db,
            organization_id,
        )

    async def list_user_roles(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ):

        return await user_role_repository.list_by_user(
            db,
            user_id,
        )


role_service = RoleService()
