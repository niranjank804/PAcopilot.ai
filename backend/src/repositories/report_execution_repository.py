import uuid
from datetime import datetime

from sqlalchemy import Interval, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.report_definition import ReportDefinition
from src.database.models.report_execution import ReportExecution
from src.reports.enums import ExecutionStatus, LEASED_EXECUTION_STATUSES


class ReportExecutionRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
    ) -> ReportExecution | None:

        result = await db.execute(
            select(ReportExecution).where(ReportExecution.id == execution_id)
        )

        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        idempotency_key: str,
    ) -> ReportExecution | None:

        result = await db.execute(
            select(ReportExecution).where(
                ReportExecution.organization_id == organization_id,
                ReportExecution.idempotency_key == idempotency_key,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        report_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReportExecution]:

        statement = select(ReportExecution).where(
            ReportExecution.organization_id == organization_id
        )

        if report_id is not None:
            statement = statement.where(ReportExecution.report_id == report_id)

        if status is not None:
            statement = statement.where(ReportExecution.status == status)

        statement = (
            statement.order_by(ReportExecution.queued_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await db.execute(statement)

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> ReportExecution:

        db.add(execution)

        await db.flush()

        await db.refresh(execution)

        return execution

    async def update(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> ReportExecution:

        await db.flush()

        await db.refresh(execution)

        return execution

    async def claim_next(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        worker_id: uuid.UUID,
        supported_formats: list[str],
        now: datetime,
        lease_expires_at: datetime,
    ) -> uuid.UUID | None:
        """Atomically hand exactly one queued execution to one worker.

        `FOR UPDATE SKIP LOCKED` inside the subquery is the whole point:
        two workers polling at the same instant take different rows
        instead of both taking the first one and racing on the update.
        Without SKIP LOCKED the second worker blocks on the first's row
        lock and then claims a row it has already been told is taken.

        The claim is also where eligibility is enforced, in SQL rather
        than after the fact:

        * organization scoping — a worker can only ever see its own
          organization's queue, and this is the server deciding that from
          the authenticated worker record, not from anything the caller
          sent;
        * the report's optional worker pin;
        * `output_formats <@ supported_formats`, so a worker that never
          proved it can export PDF is not handed a PDF job and does not
          have to bounce it back.
        """

        candidate = (
            select(ReportExecution.id)
            .join(
                ReportDefinition,
                ReportDefinition.id == ReportExecution.report_id,
            )
            .where(
                ReportExecution.organization_id == organization_id,
                ReportExecution.status == ExecutionStatus.QUEUED.value,
                ReportExecution.available_at <= now,
                or_(
                    ReportDefinition.worker_id.is_(None),
                    ReportDefinition.worker_id == worker_id,
                ),
                ReportDefinition.output_formats.contained_by(supported_formats),
            )
            # FIFO within the eligible set: the oldest occurrence should
            # not starve behind a stream of newer ones.
            .order_by(ReportExecution.available_at, ReportExecution.queued_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=ReportExecution)
        )

        statement = (
            update(ReportExecution)
            .where(ReportExecution.id == candidate.scalar_subquery())
            .values(
                status=ExecutionStatus.ASSIGNED.value,
                worker_id=worker_id,
                assigned_at=now,
                lease_expires_at=lease_expires_at,
            )
            .returning(ReportExecution.id)
            .execution_options(synchronize_session=False)
        )

        result = await db.execute(statement)

        return result.scalar_one_or_none()

    async def find_expired_leases(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        now: datetime,
        limit: int = 50,
    ) -> list[ReportExecution]:
        """Executions whose worker stopped heartbeating.

        This is how a worker crash, a power cut, or a severed network
        stops being an execution that is RUNNING forever.
        """

        statement = select(ReportExecution).where(
            ReportExecution.status.in_(
                [status.value for status in LEASED_EXECUTION_STATUSES]
            ),
            ReportExecution.lease_expires_at.is_not(None),
            ReportExecution.lease_expires_at < now,
        )

        if organization_id is not None:
            statement = statement.where(
                ReportExecution.organization_id == organization_id
            )

        result = await db.execute(statement.limit(limit))

        return list(result.scalars().all())

    async def find_stale_queued(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        now: datetime,
        limit: int = 50,
    ) -> list[ReportExecution]:
        """Executions nobody ever claimed.

        A queued job with no worker online is not "pending", it has
        failed — it just has not been told so yet. Bounded by the same
        timeout the execution itself carries, so a report configured with
        a long timeout also gets a proportionally long queue window.
        """

        statement = select(ReportExecution).where(
            ReportExecution.status == ExecutionStatus.QUEUED.value,
            # Deliberately compared against the *database* clock rather
            # than a Python `now`: several API processes sweep this table
            # and their clocks can disagree, so the only consistent
            # authority for "has this been queued too long" is the server
            # doing the comparison. It also avoids binding an aware
            # datetime against an expression SQLAlchemy cannot infer a
            # timezone-aware type for.
            ReportExecution.queued_at
            + _seconds_interval(ReportExecution.timeout_seconds)
            < func.now(),
        )

        if organization_id is not None:
            statement = statement.where(
                ReportExecution.organization_id == organization_id
            )

        result = await db.execute(statement.limit(limit))

        return list(result.scalars().all())

    async def count_active_for_worker(
        self,
        db: AsyncSession,
        worker_id: uuid.UUID,
    ) -> int:
        """How many executions a worker currently holds a lease on."""

        result = await db.execute(
            select(ReportExecution.id).where(
                and_(
                    ReportExecution.worker_id == worker_id,
                    ReportExecution.status.in_(
                        [status.value for status in LEASED_EXECUTION_STATUSES]
                    ),
                )
            )
        )

        return len(list(result.scalars().all()))


def _seconds_interval(column):
    """`timeout_seconds` (an integer column) as a SQL interval.

    Postgres will not subtract a bare integer from a timestamptz, and
    building the comparison in Python would mean fetching every queued
    row first.
    """

    return cast(func.concat(column, " seconds"), Interval)


report_execution_repository = ReportExecutionRepository()
