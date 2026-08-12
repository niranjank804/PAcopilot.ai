import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.core.logging import app_logger
from src.database.models.report_definition import ReportDefinition
from src.database.models.report_execution import ReportExecution
from src.database.models.report_worker import ReportWorker
from src.repositories.report_definition_repository import (
    report_definition_repository,
)
from src.repositories.report_execution_repository import (
    report_execution_repository,
)
from src.repositories.report_worker_repository import report_worker_repository
from src.reports.enums import (
    FORMAT_CAPABILITY,
    ExecutionStatus,
    OutputFormat,
    ReportStatus,
    RetryClass,
    TriggerType,
    WorkerCapability,
)
from src.reports.errors import (
    ReportErrorCode,
    message_for,
    retry_class_for,
)
from src.reports.state_machine import assert_transition
from src.reports.worker_service import worker_service


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """Postgres gives back tz-aware values; SQLite and hand-built rows in
    tests may not. Comparing the two raises, so normalise at the edge."""

    if value is None:
        return None

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ExecutionService:
    """The execution lifecycle: enqueue, claim, run, finish, retry, reap.

    Two properties this class is built around:

    * **Idempotency.** Creating an execution is keyed. A retried
      scheduler tick, a double-clicked button, or a replayed request
      converges on the same row instead of producing a second run (and,
      later, a second email).

    * **No unbounded waiting.** Every execution carries its own timeout
      and, once claimed, a lease. A worker that stops heartbeating loses
      the job to `reap_stale_executions()` rather than owning it forever.
    """

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def timeout_for(self, report: ReportDefinition) -> int:
        """Per-report override, clamped.

        An unclamped per-report timeout is a way for one misconfigured
        report to occupy a worker indefinitely, which is the same failure
        as having no timeout at all.
        """

        raw = (report.parameters or {}).get("timeout_seconds")

        if raw is None:
            return settings.REPORT_EXECUTION_TIMEOUT_SECONDS

        try:
            requested = int(raw)
        except (TypeError, ValueError):
            return settings.REPORT_EXECUTION_TIMEOUT_SECONDS

        return max(
            60,
            min(requested, settings.REPORT_EXECUTION_MAX_TIMEOUT_SECONDS),
        )

    @staticmethod
    def manual_idempotency_key(
        report_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> str:
        """One manual run per report, per user, per minute.

        A plain uuid would make every click a new run, so a double-click
        (or a client that retries on a slow response) launches Excel
        twice. Bucketing by minute suppresses that without blocking a
        deliberate re-run — the user waits a moment, not for a lock.
        """

        bucket = (moment or _now()).strftime("%Y%m%dT%H%M")

        return f"manual:{report_id}:{user_id}:{bucket}"

    @staticmethod
    def scheduled_idempotency_key(
        report_id: uuid.UUID,
        scheduled_for: datetime,
    ) -> str:
        """One execution per report per scheduled occurrence.

        Reserved for Phase 3 and defined here so the scheduler cannot
        invent its own key format later and quietly lose the guarantee.
        """

        return f"scheduled:{report_id}:{scheduled_for.astimezone(UTC).isoformat()}"

    async def enqueue(
        self,
        db: AsyncSession,
        *,
        report: ReportDefinition,
        organization_id: uuid.UUID,
        trigger_type: TriggerType,
        triggered_by: uuid.UUID | None,
        idempotency_key: str,
        scheduled_for: datetime | None = None,
    ) -> tuple[ReportExecution, bool]:
        """Queue one execution. Returns (execution, created).

        `created=False` means an execution for this occurrence already
        existed and is being returned unchanged — the caller should treat
        that as success, not as an error, which is what makes a retried
        request safe.
        """

        if report.status != ReportStatus.ACTIVE.value:
            raise ConflictException(
                f"This report is {report.status} and cannot be run."
            )

        if report.workbook_id is None:
            raise ValidationException(
                "This report has no workbook attached and cannot be run."
            )

        existing = await report_execution_repository.get_by_idempotency_key(
            db, organization_id, idempotency_key
        )

        if existing is not None:
            return existing, False

        await self._assert_a_worker_could_run_this(db, report, organization_id)

        now = _now()

        execution = ReportExecution(
            organization_id=organization_id,
            report_id=report.id,
            workbook_id=report.workbook_id,
            triggered_by=triggered_by,
            trigger_type=trigger_type.value,
            status=ExecutionStatus.QUEUED.value,
            idempotency_key=idempotency_key,
            correlation_id=uuid.uuid4(),
            scheduled_for=scheduled_for,
            attempt=1,
            max_attempts=settings.REPORT_MAX_ATTEMPTS,
            queued_at=now,
            available_at=now,
            timeout_seconds=self.timeout_for(report),
        )

        try:
            execution = await report_execution_repository.create(db, execution)
        except IntegrityError:
            # Lost the race against a concurrent identical request. The
            # unique index did its job; recover the winner rather than
            # surfacing a 500. Rollback first — the session is poisoned.
            await db.rollback()

            existing = await report_execution_repository.get_by_idempotency_key(
                db, organization_id, idempotency_key
            )

            if existing is None:
                raise

            return existing, False

        return execution, True

    async def _assert_a_worker_could_run_this(
        self,
        db: AsyncSession,
        report: ReportDefinition,
        organization_id: uuid.UUID,
    ) -> None:
        """Refuse at enqueue time what no worker could ever claim.

        Queuing a job that no worker is capable of running produces a
        report that sits in QUEUED until it times out — technically
        correct, useless to the person waiting. Failing now, with a
        specific reason, is the better answer.
        """

        required = self.required_capabilities(report)

        if report.worker_id is not None:
            worker = await report_worker_repository.get_by_id(
                db, report.worker_id
            )

            if (
                worker is None
                or worker.organization_id != organization_id
                or not worker_service.is_schedulable(worker)
            ):
                raise ConflictException(
                    message_for(ReportErrorCode.WORKER_OFFLINE),
                    code=ReportErrorCode.WORKER_OFFLINE.value.upper(),
                )

            if not required.issubset(worker_service.capabilities_of(worker)):
                raise ConflictException(
                    message_for(ReportErrorCode.WORKER_CAPABILITY_MISSING),
                    code=ReportErrorCode.WORKER_CAPABILITY_MISSING.value.upper(),
                )

            return

        workers = await report_worker_repository.list_by_organization(
            db, organization_id
        )

        schedulable = [
            worker for worker in workers if worker_service.is_schedulable(worker)
        ]

        eligible = [
            worker
            for worker in schedulable
            if required.issubset(worker_service.capabilities_of(worker))
        ]

        if eligible:
            return

        # Two different problems that need two different actions from the
        # operator: "start a worker" versus "this worker cannot produce
        # PDFs, install a printer driver or change the output format".
        # Collapsing them into one message sends people looking in the
        # wrong place.
        if schedulable:
            raise ConflictException(
                message_for(ReportErrorCode.WORKER_CAPABILITY_MISSING),
                code=ReportErrorCode.WORKER_CAPABILITY_MISSING.value.upper(),
            )

        raise ConflictException(
            message_for(ReportErrorCode.WORKER_OFFLINE),
            code=ReportErrorCode.WORKER_OFFLINE.value.upper(),
        )

    @staticmethod
    def required_capabilities(report: ReportDefinition) -> set[WorkerCapability]:
        """Everything the executing host must have proved it can do."""

        capabilities = {
            WorkerCapability.EXCEL,
            WorkerCapability.PAFE_AUTOMATION,
        }

        for value in report.output_formats or []:
            try:
                output_format = OutputFormat(value)
            except ValueError:
                continue

            capability = FORMAT_CAPABILITY.get(output_format)

            if capability is not None:
                capabilities.add(capability)

        return capabilities

    # ------------------------------------------------------------------
    # Worker-driven lifecycle
    # ------------------------------------------------------------------

    async def claim_next(
        self,
        db: AsyncSession,
        worker: ReportWorker,
    ) -> ReportExecution | None:
        """Hand this worker at most one execution.

        Reaping runs first and only for this worker's organization: a
        poll is the natural moment to notice that some *other* worker's
        lease lapsed, and doing it here means the POC needs no separate
        scheduler process to recover from a crash. Phase 3 moves this to
        a real periodic task; the method is written to be safe from both.
        """

        await self.reap_stale_executions(
            db, organization_id=worker.organization_id
        )

        capabilities = worker_service.capabilities_of(worker)

        required = {WorkerCapability.EXCEL, WorkerCapability.PAFE_AUTOMATION}

        if not required.issubset(capabilities):
            # Not an error — a worker whose Excel probe failed simply has
            # nothing it can be given. It keeps heartbeating and becomes
            # eligible again once its next `doctor` run succeeds.
            return None

        supported_formats = sorted(
            output_format.value
            for output_format, capability in FORMAT_CAPABILITY.items()
            if capability in capabilities
        )

        now = _now()

        execution_id = await report_execution_repository.claim_next(
            db,
            organization_id=worker.organization_id,
            worker_id=worker.id,
            supported_formats=supported_formats,
            now=now,
            lease_expires_at=now
            + timedelta(seconds=settings.REPORT_EXECUTION_LEASE_SECONDS),
        )

        if execution_id is None:
            return None

        return await report_execution_repository.get_by_id(db, execution_id)

    async def mark_started(
        self,
        db: AsyncSession,
        execution: ReportExecution,
        worker: ReportWorker,
    ) -> ReportExecution:

        self._assert_owned_by(execution, worker)

        assert_transition(
            ExecutionStatus(execution.status), ExecutionStatus.RUNNING
        )

        now = _now()

        execution.status = ExecutionStatus.RUNNING.value
        execution.started_at = now
        execution.lease_expires_at = now + timedelta(
            seconds=settings.REPORT_EXECUTION_LEASE_SECONDS
        )

        return await report_execution_repository.update(db, execution)

    async def extend_lease(
        self,
        db: AsyncSession,
        execution: ReportExecution,
        worker: ReportWorker,
        *,
        step: str | None = None,
    ) -> ReportExecution:
        """A running worker saying "still here".

        Also enforces the execution's own timeout: a worker that keeps
        heartbeating while Excel is wedged would otherwise hold the lease
        indefinitely. The deadline is measured from `started_at`, so a
        long queue wait does not eat into the run's allowance.
        """

        self._assert_owned_by(execution, worker)

        if ExecutionStatus(execution.status) not in {
            ExecutionStatus.ASSIGNED,
            ExecutionStatus.RUNNING,
        }:
            raise ConflictException(
                "This execution is no longer running.",
                code="INVALID_EXECUTION_TRANSITION",
            )

        now = _now()
        started = _aware(execution.started_at) or _aware(execution.assigned_at)

        if started is not None:
            deadline = started + timedelta(seconds=execution.timeout_seconds)

            if now > deadline:
                await self.fail(
                    db,
                    execution,
                    worker=worker,
                    error_code=ReportErrorCode.EXECUTION_TIMEOUT,
                    target_status=ExecutionStatus.TIMED_OUT,
                    diagnostics={
                        "timeout_seconds": execution.timeout_seconds,
                        "step": step,
                    },
                )

                raise ConflictException(
                    message_for(ReportErrorCode.EXECUTION_TIMEOUT),
                    code=ReportErrorCode.EXECUTION_TIMEOUT.value.upper(),
                )

        execution.lease_expires_at = now + timedelta(
            seconds=settings.REPORT_EXECUTION_LEASE_SECONDS
        )

        if step:
            diagnostics = dict(execution.diagnostics or {})
            diagnostics["step"] = str(step)[:100]
            execution.diagnostics = diagnostics

        return await report_execution_repository.update(db, execution)

    async def succeed(
        self,
        db: AsyncSession,
        execution: ReportExecution,
        worker: ReportWorker,
        *,
        trace_log: str | None = None,
        diagnostics: dict | None = None,
    ) -> ReportExecution:

        self._assert_owned_by(execution, worker)

        assert_transition(
            ExecutionStatus(execution.status), ExecutionStatus.SUCCEEDED
        )

        execution.status = ExecutionStatus.SUCCEEDED.value

        self._finalize(execution, trace_log=trace_log, diagnostics=diagnostics)

        return await report_execution_repository.update(db, execution)

    async def fail(
        self,
        db: AsyncSession,
        execution: ReportExecution,
        *,
        worker: ReportWorker | None,
        error_code: ReportErrorCode,
        target_status: ExecutionStatus = ExecutionStatus.FAILED,
        trace_log: str | None = None,
        diagnostics: dict | None = None,
    ) -> ReportExecution:

        if worker is not None:
            self._assert_owned_by(execution, worker)

        assert_transition(ExecutionStatus(execution.status), target_status)

        retry_class = retry_class_for(error_code)

        execution.status = target_status.value
        execution.error_code = error_code.value
        # The stored message is always ours. A driver string, a COM error
        # or a stack trace from the worker can carry a path, a host, or a
        # credential, and this field is shown in the UI.
        execution.error_message = message_for(error_code)
        execution.retry_class = retry_class.value

        self._finalize(execution, trace_log=trace_log, diagnostics=diagnostics)

        return await report_execution_repository.update(db, execution)

    async def cancel(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> ReportExecution:

        assert_transition(
            ExecutionStatus(execution.status), ExecutionStatus.CANCELLED
        )

        execution.status = ExecutionStatus.CANCELLED.value
        execution.error_code = ReportErrorCode.CANCELLED.value
        execution.error_message = message_for(ReportErrorCode.CANCELLED)
        execution.retry_class = RetryClass.NON_RETRYABLE.value

        self._finalize(execution)

        return await report_execution_repository.update(db, execution)

    # ------------------------------------------------------------------
    # Retry and recovery
    # ------------------------------------------------------------------

    def can_retry(self, execution: ReportExecution) -> bool:
        if execution.retry_class != RetryClass.RETRYABLE.value:
            return False

        return execution.attempt < execution.max_attempts

    def backoff_seconds(self, attempt: int) -> int:
        """Exponential, capped, and applied to the *next* attempt.

        Retrying a TM1 outage every few seconds turns one failure into a
        load test against a server that is already unhappy.
        """

        delay = settings.REPORT_RETRY_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))

        return min(delay, settings.REPORT_RETRY_BACKOFF_MAX_SECONDS)

    async def create_retry(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> ReportExecution | None:
        """Spawn the replacement attempt, if one is warranted.

        The failed row moves to RETRYING and stays terminal. The new row
        carries `parent_execution_id` and a derived idempotency key, so
        the chain is inspectable and a second call to this method finds
        the existing retry instead of creating another.
        """

        if not self.can_retry(execution):
            return None

        next_attempt = execution.attempt + 1
        key = f"{execution.idempotency_key}#a{next_attempt}"

        existing = await report_execution_repository.get_by_idempotency_key(
            db, execution.organization_id, key
        )

        if existing is not None:
            return existing

        now = _now()

        retry = ReportExecution(
            organization_id=execution.organization_id,
            report_id=execution.report_id,
            workbook_id=execution.workbook_id,
            triggered_by=execution.triggered_by,
            trigger_type=TriggerType.RETRY.value,
            status=ExecutionStatus.QUEUED.value,
            idempotency_key=key,
            # Same correlation id as the original: this is one logical
            # report run being attempted again, and following it across
            # attempts is the whole point of the field.
            correlation_id=execution.correlation_id,
            scheduled_for=execution.scheduled_for,
            attempt=next_attempt,
            max_attempts=execution.max_attempts,
            parent_execution_id=execution.id,
            queued_at=now,
            available_at=now
            + timedelta(seconds=self.backoff_seconds(execution.attempt)),
            timeout_seconds=execution.timeout_seconds,
        )

        try:
            retry = await report_execution_repository.create(db, retry)
        except IntegrityError:
            await db.rollback()

            existing = await report_execution_repository.get_by_idempotency_key(
                db, execution.organization_id, key
            )

            if existing is None:
                raise

            return existing

        # Only after the replacement exists — if this ordering were
        # reversed and the insert failed, the original would be marked
        # RETRYING with nothing actually retrying it.
        assert_transition(
            ExecutionStatus(execution.status), ExecutionStatus.RETRYING
        )
        execution.status = ExecutionStatus.RETRYING.value

        await report_execution_repository.update(db, execution)

        return retry

    async def reap_stale_executions(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> int:
        """Time out what the world has moved past, and retry what should be.

        Two populations:

        * leases that lapsed — the worker crashed, lost power, or lost
          the network mid-run;
        * queued executions nobody claimed within their own timeout —
          usually "no worker was ever online".
        """

        now = _now()
        reaped = 0

        expired = await report_execution_repository.find_expired_leases(
            db, organization_id=organization_id, now=now
        )

        for execution in expired:
            await self.fail(
                db,
                execution,
                worker=None,
                error_code=ReportErrorCode.WORKER_LEASE_EXPIRED,
                target_status=ExecutionStatus.TIMED_OUT,
                diagnostics={
                    "reaped": True,
                    "lease_expired_at": _aware(
                        execution.lease_expires_at
                    ).isoformat()
                    if execution.lease_expires_at
                    else None,
                },
            )

            await self.create_retry(db, execution)

            reaped += 1

        stale = await report_execution_repository.find_stale_queued(
            db, organization_id=organization_id, now=now
        )

        for execution in stale:
            await self.fail(
                db,
                execution,
                worker=None,
                error_code=ReportErrorCode.WORKER_OFFLINE,
                target_status=ExecutionStatus.TIMED_OUT,
                diagnostics={"reaped": True, "never_claimed": True},
            )

            reaped += 1

        if reaped:
            app_logger.info(
                f"report_automation reaped {reaped} stale execution(s)"
            )

        return reaped

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def list_executions(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        report_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReportExecution]:
        """History for one organization.

        `status` is validated against the enum rather than passed
        through: an unrecognised value returns nothing rather than
        becoming an arbitrary string in a WHERE clause.
        """

        if status is not None:
            try:
                status = ExecutionStatus(status).value
            except ValueError:
                raise ValidationException(f"Unknown execution status: {status}")

        return await report_execution_repository.list_by_organization(
            db,
            organization_id,
            report_id=report_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportExecution:

        execution = await report_execution_repository.get_by_id(
            db, execution_id
        )

        if execution is None or execution.organization_id != organization_id:
            raise NotFoundException("Execution not found.")

        return execution

    async def get_report_for_execution(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> ReportDefinition:

        report = await report_definition_repository.get_by_id(
            db, execution.report_id
        )

        if report is None or report.organization_id != execution.organization_id:
            raise NotFoundException("Report not found.")

        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_owned_by(
        execution: ReportExecution,
        worker: ReportWorker,
    ) -> None:
        """A worker may only touch the execution it actually holds.

        Both halves matter. The organization check stops a worker in one
        tenant from addressing another tenant's execution by id; the
        worker check stops a worker inside the same tenant from finishing
        (or failing) a job that a different machine is running.
        """

        if execution.organization_id != worker.organization_id:
            raise NotFoundException("Execution not found.")

        if execution.worker_id != worker.id:
            raise NotFoundException("Execution not found.")

    @staticmethod
    def _finalize(
        execution: ReportExecution,
        *,
        trace_log: str | None = None,
        diagnostics: dict | None = None,
    ) -> None:
        now = _now()

        execution.completed_at = now
        # The lease is released explicitly: a terminal execution with a
        # live lease would keep showing up for the reaper.
        execution.lease_expires_at = None

        started = _aware(execution.started_at) or _aware(execution.queued_at)

        if started is not None:
            execution.duration_ms = max(
                0, int((now - started).total_seconds() * 1000)
            )

        if trace_log:
            execution.trace_log = trace_log[
                : settings.REPORT_TRACE_LOG_MAX_CHARS
            ]

        if diagnostics:
            merged = dict(execution.diagnostics or {})
            merged.update(diagnostics)
            execution.diagnostics = merged


execution_service = ExecutionService()
