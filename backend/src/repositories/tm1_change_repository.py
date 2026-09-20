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

    async def lock_for_update(
        self,
        db: AsyncSession,
        change_id: uuid.UUID,
    ) -> TM1Change | None:
        """The row, locked until this transaction ends and re-read from the
        database.

        A status check made after this sees what any concurrent executor
        has already committed, and a concurrent executor waits here until
        this transaction commits — so two people pressing Execute on the
        same draft produce one execution and one 409, not two writes to
        TM1. populate_existing: the session may already hold this row
        from the route's own lookup, and the point is the fresh state.
        """

        result = await db.execute(
            select(TM1Change)
            .where(TM1Change.id == change_id)
            .with_for_update()
            .execution_options(populate_existing=True)
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

    async def list_open_drafts(
        self,
        db: AsyncSession,
        *,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
        created_by: uuid.UUID,
        change_type: str,
        target_name: str,
    ) -> list[TM1Change]:
        """Still-executable drafts one author has open against one target."""

        result = await db.execute(
            select(TM1Change)
            .where(
                TM1Change.connection_id == connection_id,
                TM1Change.organization_id == organization_id,
                TM1Change.created_by == created_by,
                TM1Change.change_type == change_type,
                TM1Change.target_name == target_name,
                TM1Change.status == "draft",
            )
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
