import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_worker import ReportWorker


class ReportWorkerRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
    ) -> ReportWorker | None:

        result = await db.execute(
            select(ReportWorker).where(ReportWorker.id == worker_id)
        )

        return result.scalar_one_or_none()

    async def get_by_enrollment_token_hash(
        self,
        db: AsyncSession,
        token_hash: str,
    ) -> ReportWorker | None:
        """Look a worker up by enrollment secret alone.

        Deliberately not organization-scoped: the caller is an
        unauthenticated worker process that has a token and nothing else.
        The token *is* the organization binding — it was minted for one
        worker row, which carries its own organization_id, and the
        enrollment handler uses that rather than anything the caller
        sends. This is also why the token hash column is uniquely indexed.
        """

        result = await db.execute(
            select(ReportWorker).where(
                ReportWorker.enrollment_token_hash == token_hash
            )
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportWorker]:

        result = await db.execute(
            select(ReportWorker)
            .where(ReportWorker.organization_id == organization_id)
            .order_by(ReportWorker.name)
        )

        return list(result.scalars().all())

    async def get_by_name(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        name: str,
    ) -> ReportWorker | None:

        result = await db.execute(
            select(ReportWorker).where(
                ReportWorker.organization_id == organization_id,
                ReportWorker.name == name,
            )
        )

        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        worker: ReportWorker,
    ) -> ReportWorker:

        db.add(worker)

        await db.flush()

        await db.refresh(worker)

        return worker

    async def update(
        self,
        db: AsyncSession,
        worker: ReportWorker,
    ) -> ReportWorker:

        await db.flush()

        await db.refresh(worker)

        return worker


report_worker_repository = ReportWorkerRepository()
