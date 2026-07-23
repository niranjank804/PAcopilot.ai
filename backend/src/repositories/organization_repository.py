from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.organization import Organization


class OrganizationRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        organization_id,
    ) -> Organization | None:

        result = await db.execute(
            select(Organization).where(Organization.id == organization_id)
        )

        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        db: AsyncSession,
        code: str,
    ) -> Organization | None:

        result = await db.execute(
            select(Organization).where(Organization.code == code)
        )

        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        organization: Organization,
    ) -> Organization:

        db.add(organization)

        await db.flush()

        await db.refresh(organization)

        return organization

    async def update(
        self,
        db: AsyncSession,
        organization: Organization,
    ) -> Organization:

        await db.flush()
        await db.refresh(organization)

        return organization

    async def delete(
        self,
        db: AsyncSession,
        organization: Organization,
    ) -> None:

        await db.delete(organization)
        await db.flush()


organization_repository = OrganizationRepository()
