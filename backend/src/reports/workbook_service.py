import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ConflictException, NotFoundException
from src.database.models.report_workbook import ReportWorkbook
from src.repositories.report_definition_repository import (
    report_definition_repository,
)
from src.repositories.report_workbook_repository import (
    report_workbook_repository,
)
from src.reports.storage import get_storage_backend
from src.reports.validation import (
    checksum,
    sanitize_filename,
    validate_workbook_bytes,
)

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_MIME_BY_EXTENSION = {
    ".xlsx": XLSX_MIME,
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".xlsb": "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
}


class WorkbookService:
    """Custody of the .xlsm/.xlsx files a worker will actually open.

    The rule this service enforces is that nothing about an uploaded file
    is taken on trust: not its name, not its declared content type, not
    its size header. What is stored is a sanitized name, a server-derived
    MIME type, the measured size, and a SHA-256 the worker re-verifies
    before Excel is ever launched.
    """

    async def upload(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str | None,
        filename: str,
        file_bytes: bytes,
        description: str | None = None,
    ) -> ReportWorkbook:

        safe_filename = sanitize_filename(filename)

        validate_workbook_bytes(
            file_bytes,
            max_bytes=settings.REPORT_MAX_WORKBOOK_BYTES,
        )

        extension = safe_filename[safe_filename.rfind(".") :].lower()

        # Derived from the validated extension, never from the browser's
        # Content-Type header — that header is caller-controlled and is a
        # common way to get a file served back with the wrong type.
        content_type = _MIME_BY_EXTENSION.get(extension, XLSX_MIME)

        display_name = (name or safe_filename).strip()[:150]

        version = await report_workbook_repository.next_version(
            db, organization_id, display_name
        )

        reference = await get_storage_backend().put(
            db,
            organization_id=organization_id,
            data=file_bytes,
            content_type=content_type,
        )

        workbook = ReportWorkbook(
            organization_id=organization_id,
            created_by=user_id,
            name=display_name,
            filename=safe_filename,
            content_type=content_type,
            checksum=checksum(file_bytes),
            size_bytes=len(file_bytes),
            version=version,
            storage_reference=reference,
            status="active",
            description=description,
        )

        return await report_workbook_repository.create(db, workbook)

    async def list_workbooks(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[ReportWorkbook]:

        return await report_workbook_repository.list_by_organization(
            db, organization_id
        )

    async def get_workbook(
        self,
        db: AsyncSession,
        workbook_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportWorkbook:

        workbook = await report_workbook_repository.get_by_id(db, workbook_id)

        if workbook is None or workbook.organization_id != organization_id:
            raise NotFoundException("Workbook not found.")

        return workbook

    async def get_content(
        self,
        db: AsyncSession,
        workbook: ReportWorkbook,
    ) -> bytes:
        """Fetch the bytes, re-checking integrity on the way out.

        The checksum is verified here as well as on the worker. Verifying
        only on the worker would mean silent corruption at rest is
        detected as a *report* failure attributed to the customer's
        environment, which is the wrong place to look.
        """

        data = await get_storage_backend().get(
            db,
            organization_id=workbook.organization_id,
            reference=workbook.storage_reference,
        )

        if checksum(data) != workbook.checksum:
            raise ConflictException(
                "The stored workbook failed its integrity check and was not "
                "served.",
                code="WORKBOOK_CHECKSUM_MISMATCH",
            )

        return data

    async def delete(
        self,
        db: AsyncSession,
        workbook_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        workbook = await self.get_workbook(db, workbook_id, organization_id)

        in_use = await report_definition_repository.count_by_workbook(
            db, organization_id, workbook_id
        )

        if in_use:
            raise ConflictException(
                f"This workbook is used by {in_use} report(s). Update or "
                "delete those reports first."
            )

        await get_storage_backend().delete(
            db,
            organization_id=organization_id,
            reference=workbook.storage_reference,
        )

        await db.delete(workbook)

        await db.flush()


workbook_service = WorkbookService()
