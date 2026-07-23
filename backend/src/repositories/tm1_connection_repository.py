import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_connection import TM1Connection


class TM1ConnectionRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
    ) -> TM1Connection | None:

        result = await db.execute(
            select(TM1Connection).where(TM1Connection.id == connection_id)
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[TM1Connection]:

        result = await db.execute(
            select(TM1Connection)
            .where(TM1Connection.organization_id == organization_id)
            .order_by(TM1Connection.name)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        connection: TM1Connection,
    ) -> TM1Connection:

        db.add(connection)

        await db.flush()

        await db.refresh(connection)

        return connection

    async def update(
        self,
        db: AsyncSession,
        connection: TM1Connection,
    ) -> TM1Connection:

        await db.flush()

        await db.refresh(connection)

        return connection

    async def delete(
        self,
        db: AsyncSession,
        connection: TM1Connection,
    ) -> None:

        await db.delete(connection)
        await db.flush()


tm1_connection_repository = TM1ConnectionRepository()
