import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_artifact import ReportArtifact


class ReportArtifactRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        artifact_id: uuid.UUID,
    ) -> ReportArtifact | None:

        result = await db.execute(
            select(ReportArtifact).where(ReportArtifact.id == artifact_id)
        )

        return result.scalar_one_or_none()

    async def get_by_execution_and_format(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        output_format: str,
    ) -> ReportArtifact | None:
        """Backs idempotent upload: a retried upload finds its own row."""

        result = await db.execute(
            select(ReportArtifact).where(
                ReportArtifact.report_execution_id == execution_id,
                ReportArtifact.output_format == output_format,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
    ) -> list[ReportArtifact]:

        result = await db.execute(
            select(ReportArtifact)
            .where(ReportArtifact.report_execution_id == execution_id)
            .order_by(ReportArtifact.output_format)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        artifact: ReportArtifact,
    ) -> ReportArtifact:

        db.add(artifact)

        await db.flush()

        await db.refresh(artifact)

        return artifact


report_artifact_repository = ReportArtifactRepository()
