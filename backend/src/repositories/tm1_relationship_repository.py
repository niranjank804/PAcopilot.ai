import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_relationship import TM1Relationship


class TM1RelationshipRepository:

    async def create(
        self,
        db: AsyncSession,
        relationship: TM1Relationship,
    ) -> TM1Relationship:

        db.add(relationship)

        await db.flush()

        await db.refresh(relationship)

        return relationship

    async def list_by_from_object(
        self,
        db: AsyncSession,
        from_object_id: uuid.UUID,
        relationship_type: str | None = None,
    ) -> list[TM1Relationship]:

        query = select(TM1Relationship).where(
            TM1Relationship.from_object_id == from_object_id
        )

        if relationship_type is not None:
            query = query.where(TM1Relationship.relationship_type == relationship_type)

        result = await db.execute(query)

        return list(result.scalars().all())

    async def list_by_to_object(
        self,
        db: AsyncSession,
        to_object_id: uuid.UUID,
        relationship_type: str | None = None,
    ) -> list[TM1Relationship]:

        query = select(TM1Relationship).where(
            TM1Relationship.to_object_id == to_object_id
        )

        if relationship_type is not None:
            query = query.where(TM1Relationship.relationship_type == relationship_type)

        result = await db.execute(query)

        return list(result.scalars().all())

    async def list_by_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
    ) -> list[TM1Relationship]:

        result = await db.execute(
            select(TM1Relationship).where(
                TM1Relationship.connection_id == connection_id
            )
        )

        return list(result.scalars().all())

    async def delete_by_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
    ) -> None:

        await db.execute(
            delete(TM1Relationship).where(
                TM1Relationship.connection_id == connection_id
            )
        )
        await db.flush()


tm1_relationship_repository = TM1RelationshipRepository()
