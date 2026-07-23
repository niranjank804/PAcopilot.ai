from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.role import Role


class RoleRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        role_id,
    ) -> Role | None:

        result = await db.execute(
            select(Role).where(Role.id == role_id)
        )

        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        db: AsyncSession,
        organization_id,
        name: str,
    ) -> Role | None:

        result = await db.execute(
            select(Role).where(
                Role.organization_id == organization_id,
                Role.name == name,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id,
    ) -> list[Role]:

        result = await db.execute(
            select(Role)
            .where(Role.organization_id == organization_id)
            .order_by(Role.name)
        )

        return list(result.scalars().all())

    async def get_system_role(
        self,
        db: AsyncSession,
        name: str,
    ) -> Role | None:

        result = await db.execute(
            select(Role).where(
                Role.organization_id.is_(None),
                Role.name == name,
                Role.is_system.is_(True),
            )
        )

        return result.scalar_one_or_none()

    async def list_visible_to_organization(
        self,
        db: AsyncSession,
        organization_id,
    ) -> list[Role]:

        result = await db.execute(
            select(Role)
            .where(
                or_(
                    Role.organization_id == organization_id,
                    Role.organization_id.is_(None),
                )
            )
            .order_by(Role.name)
        )

        return list(result.scalars().all())

    async def list_system_roles(
        self,
        db: AsyncSession,
    ) -> list[Role]:

        result = await db.execute(
            select(Role)
            .where(Role.is_system.is_(True))
            .order_by(Role.name)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        role: Role,
    ) -> Role:

        db.add(role)

        await db.flush()

        await db.refresh(role)

        return role

    async def update(
        self,
        db: AsyncSession,
        role: Role,
    ) -> Role:

        await db.flush()
        await db.refresh(role)

        return role

    async def delete(
        self,
        db: AsyncSession,
        role: Role,
    ) -> None:

        await db.delete(role)
        await db.flush()


role_repository = RoleRepository()
