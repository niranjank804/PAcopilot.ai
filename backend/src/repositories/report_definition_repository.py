import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_definition import ReportDefinition


class ReportDefinitionRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
    ) -> ReportDefinition | None:

        result = await db.execute(
            select(ReportDefinition).where(ReportDefinition.id == report_id)
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportDefinition]:

        result = await db.execute(
            select(ReportDefinition)
            .where(ReportDefinition.organization_id == organization_id)
            .order_by(ReportDefinition.name)
        )

        return list(result.scalars().all())

    async def count_by_workbook(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        workbook_id: uuid.UUID,
    ) -> int:
        """Used to refuse a workbook delete that would orphan reports."""

        result = await db.execute(
            select(ReportDefinition.id).where(
                ReportDefinition.organization_id == organization_id,
                ReportDefinition.workbook_id == workbook_id,
            )
        )

        return len(list(result.scalars().all()))

    async def create(
        self,
        db: AsyncSession,
        report: ReportDefinition,
    ) -> ReportDefinition:

        db.add(report)

        await db.flush()

        await db.refresh(report)

        return report

    async def update(
        self,
        db: AsyncSession,
        report: ReportDefinition,
    ) -> ReportDefinition:

        await db.flush()

        await db.refresh(report)

        return report


report_definition_repository = ReportDefinitionRepository()
