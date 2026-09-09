import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.role import Role
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

    async def role_names_by_user(
        self,
        db: AsyncSession,
        user_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[str]]:
        """Role names for many users in one query.

        The Users page lists every member of an organization. Fetching
        roles per row would be one request per user — exactly the N+1
        the dedicated /users/{id}/roles endpoint invites when used from
        a list. One join, grouped in Python, keeps the list endpoint at
        two queries regardless of size.
        """

        if not user_ids:
            return {}

        result = await db.execute(
            select(UserRole.user_id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .order_by(Role.name)
        )

        names: dict[uuid.UUID, list[str]] = {}

        for user_id, role_name in result.all():
            names.setdefault(user_id, []).append(role_name)

        return names

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
