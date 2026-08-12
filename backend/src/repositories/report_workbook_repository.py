import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_workbook import ReportWorkbook


class ReportWorkbookRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        workbook_id: uuid.UUID,
    ) -> ReportWorkbook | None:

        result = await db.execute(
            select(ReportWorkbook).where(ReportWorkbook.id == workbook_id)
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportWorkbook]:

        result = await db.execute(
            select(ReportWorkbook)
            .where(ReportWorkbook.organization_id == organization_id)
            .order_by(ReportWorkbook.name, ReportWorkbook.version.desc())
        )

        return list(result.scalars().all())

    async def next_version(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        name: str,
    ) -> int:
        """Version numbers are per (organization, workbook name).

        Computed rather than stored on a parent row because a workbook has
        no parent entity — each upload is its own immutable row, which is
        what keeps an old execution's reference truthful.
        """

        result = await db.execute(
            select(func.max(ReportWorkbook.version)).where(
                ReportWorkbook.organization_id == organization_id,
                ReportWorkbook.name == name,
            )
        )

        current = result.scalar_one_or_none()

        return (current or 0) + 1

    async def create(
        self,
        db: AsyncSession,
        workbook: ReportWorkbook,
    ) -> ReportWorkbook:

        db.add(workbook)

        await db.flush()

        await db.refresh(workbook)

        return workbook

    async def update(
        self,
        db: AsyncSession,
        workbook: ReportWorkbook,
    ) -> ReportWorkbook:

        await db.flush()

        await db.refresh(workbook)

        return workbook


report_workbook_repository = ReportWorkbookRepository()
