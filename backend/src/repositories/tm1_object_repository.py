import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_object import TM1Object


class TM1ObjectRepository:

    async def create(
        self,
        db: AsyncSession,
        obj: TM1Object,
    ) -> TM1Object:

        db.add(obj)

        await db.flush()

        await db.refresh(obj)

        return obj

    async def list_by_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        object_type: str | None = None,
    ) -> list[TM1Object]:

        query = select(TM1Object).where(TM1Object.connection_id == connection_id)

        if object_type is not None:
            query = query.where(TM1Object.object_type == object_type)

        result = await db.execute(query)

        return list(result.scalars().all())

    async def get_by_id(
        self,
        db: AsyncSession,
        object_id: uuid.UUID,
    ) -> TM1Object | None:

        result = await db.execute(
            select(TM1Object).where(TM1Object.id == object_id)
        )

        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        object_type: str,
        name: str,
    ) -> TM1Object | None:

        result = await db.execute(
            select(TM1Object).where(
                TM1Object.connection_id == connection_id,
                TM1Object.object_type == object_type,
                TM1Object.name == name,
            )
        )

        return result.scalar_one_or_none()

    async def delete_by_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
    ) -> None:

        await db.execute(
            delete(TM1Object).where(TM1Object.connection_id == connection_id)
        )
        await db.flush()


tm1_object_repository = TM1ObjectRepository()
