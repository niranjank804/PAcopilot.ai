import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_change import TM1Change


class TM1ChangeRepository:

    async def create(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> TM1Change:

        db.add(change)

        await db.flush()

        await db.refresh(change)

        return change

    async def get_by_id(
        self,
        db: AsyncSession,
        change_id: uuid.UUID,
    ) -> TM1Change | None:

        result = await db.execute(
            select(TM1Change).where(TM1Change.id == change_id)
        )

        return result.scalar_one_or_none()

    async def list_by_connection(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
    ) -> list[TM1Change]:

        result = await db.execute(
            select(TM1Change)
            .where(TM1Change.connection_id == connection_id)
            .order_by(TM1Change.created_at.desc())
        )

        return list(result.scalars().all())

    async def update(
        self,
        db: AsyncSession,
        change: TM1Change,
    ) -> TM1Change:

        await db.flush()
        await db.refresh(change)

        return change


tm1_change_repository = TM1ChangeRepository()
