import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.database.models.report_definition import ReportDefinition
from src.database.models.report_execution import ReportExecution
from src.repositories.report_definition_repository import (
    report_definition_repository,
)
from src.repositories.report_worker_repository import report_worker_repository
from src.repositories.tm1_connection_repository import (
    tm1_connection_repository,
)
from src.reports.enums import (
    ApprovalStatus,
    ReportStatus,
    TriggerType,
)
from src.reports.execution_service import execution_service
from src.reports.validation import (
    validate_output_formats,
    validate_report_type,
)
from src.reports.workbook_service import workbook_service


class ReportService:
    """Report definitions, and the one human-initiated way to run them.

    There is deliberately no path in this class by which anything other
    than an explicit, permission-checked human action starts a report.
    Scheduling (Phase 3) is where automatic execution arrives, and STET
    approval (Phase 6) is what will gate it.
    """

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        description: str | None,
        report_type: str,
        workbook_id: uuid.UUID | None,
        connection_id: uuid.UUID | None,
        worker_id: uuid.UUID | None,
        output_formats: list[str],
        parameters: dict | None,
    ) -> ReportDefinition:

        name = (name or "").strip()

        if not name:
            raise ValidationException("A report name is required.")

        validated_type = validate_report_type(report_type)
        validated_formats = validate_output_formats(output_formats)

        # Every referenced resource is re-resolved inside this
        # organization. Accepting an id and trusting it is how a
        # cross-tenant reference gets stored and then acted on later by a
        # worker that has no way to tell it was wrong.
        if workbook_id is not None:
            await workbook_service.get_workbook(db, workbook_id, organization_id)
        else:
            raise ValidationException(
                "A workbook is required for a PAfE workbook report."
            )

        if connection_id is not None:
            await self._resolve_connection(db, connection_id, organization_id)

        if worker_id is not None:
            await self._resolve_worker(db, worker_id, organization_id)

        report = ReportDefinition(
            organization_id=organization_id,
            created_by=user_id,
            name=name,
            description=description,
            report_type=validated_type.value,
            workbook_id=workbook_id,
            connection_id=connection_id,
            worker_id=worker_id,
            parameters=parameters or {},
            output_formats=[fmt.value for fmt in validated_formats],
            delivery_configuration={},
            status=ReportStatus.ACTIVE.value,
            approval_status=ApprovalStatus.NOT_REQUIRED.value,
        )

        return await report_definition_repository.create(db, report)

    async def list_reports(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportDefinition]:

        return await report_definition_repository.list_by_organization(
            db, organization_id
        )

    async def get_report(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportDefinition:

        report = await report_definition_repository.get_by_id(db, report_id)

        if report is None or report.organization_id != organization_id:
            raise NotFoundException("Report not found.")

        return report

    async def update(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        workbook_id: uuid.UUID | None = None,
        connection_id: uuid.UUID | None = None,
        worker_id: uuid.UUID | None = None,
        output_formats: list[str] | None = None,
        parameters: dict | None = None,
    ) -> ReportDefinition:

        report = await self.get_report(db, report_id, organization_id)

        if name is not None:
            trimmed = name.strip()

            if not trimmed:
                raise ValidationException("A report name is required.")

            report.name = trimmed

        if description is not None:
            report.description = description

        if workbook_id is not None:
            await workbook_service.get_workbook(db, workbook_id, organization_id)
            report.workbook_id = workbook_id

        if connection_id is not None:
            await self._resolve_connection(db, connection_id, organization_id)
            report.connection_id = connection_id

        if worker_id is not None:
            await self._resolve_worker(db, worker_id, organization_id)
            report.worker_id = worker_id

        if output_formats is not None:
            report.output_formats = [
                fmt.value for fmt in validate_output_formats(output_formats)
            ]

        if parameters is not None:
            report.parameters = parameters

        return await report_definition_repository.update(db, report)

    async def set_status(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        status: ReportStatus,
    ) -> ReportDefinition:

        report = await self.get_report(db, report_id, organization_id)

        report.status = status.value

        return await report_definition_repository.update(db, report)

    async def archive(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportDefinition:
        """Reports are archived, never hard-deleted.

        Executions reference the definition with ON DELETE RESTRICT
        precisely so that history cannot be erased by removing the report
        it describes. Archiving keeps the audit trail intact and takes
        the report out of every list and every queue.
        """

        return await self.set_status(
            db, report_id, organization_id, status=ReportStatus.ARCHIVED
        )

    async def run_now(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> tuple[ReportExecution, bool]:
        """A person pressing Run. The only trigger that exists today."""

        report = await self.get_report(db, report_id, organization_id)

        return await execution_service.enqueue(
            db,
            report=report,
            organization_id=organization_id,
            trigger_type=TriggerType.MANUAL,
            triggered_by=user_id,
            idempotency_key=execution_service.manual_idempotency_key(
                report.id, user_id
            ),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    async def _resolve_connection(
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        connection = await tm1_connection_repository.get_by_id(
            db, connection_id
        )

        if connection is None or connection.organization_id != organization_id:
            raise NotFoundException("TM1 connection not found.")

        if not connection.is_active:
            raise ConflictException(
                "That TM1 connection is inactive."
            )

    @staticmethod
    async def _resolve_worker(
        db: AsyncSession,
        worker_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        worker = await report_worker_repository.get_by_id(db, worker_id)

        if worker is None or worker.organization_id != organization_id:
            raise NotFoundException("Worker not found.")


report_service = ReportService()
