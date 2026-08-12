import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ConflictException, NotFoundException, ValidationException
from src.database.models.report_artifact import ReportArtifact
from src.database.models.report_execution import ReportExecution
from src.repositories.report_artifact_repository import (
    report_artifact_repository,
)
from src.reports.enums import OutputFormat
from src.reports.storage import get_storage_backend
from src.reports.validation import checksum

MIME_BY_FORMAT = {
    OutputFormat.XLSX: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    OutputFormat.PDF: "application/pdf",
    OutputFormat.CSV: "text/csv",
}


class ArtifactService:
    """Files produced by an execution, and who may read them.

    Access is always resolved through the owning execution, never from
    the artifact id alone. That is what makes an artifact identifier
    useless to anyone outside the organization even if it leaks — the
    "artifact URL reuse" case in the red-team list.
    """

    async def record_upload(
        self,
        db: AsyncSession,
        *,
        execution: ReportExecution,
        output_format: OutputFormat,
        filename: str,
        data: bytes,
        declared_checksum: str | None = None,
    ) -> tuple[ReportArtifact, bool]:
        """Store one artifact. Returns (artifact, created).

        Idempotent per (execution, format): a worker that uploaded
        successfully but lost the response retries, and gets its existing
        artifact back instead of creating a duplicate. The retry is only
        accepted as the same artifact if the bytes match — different
        content under the same slot is a conflict, not a retry.
        """

        if not data:
            raise ValidationException("The uploaded artifact is empty.")

        if len(data) > settings.REPORT_MAX_ARTIFACT_BYTES:
            raise ValidationException(
                "The generated report exceeds the maximum artifact size."
            )

        computed = checksum(data)

        if declared_checksum and declared_checksum.lower() != computed:
            raise ValidationException(
                "The uploaded artifact did not match its declared checksum."
            )

        existing = await report_artifact_repository.get_by_execution_and_format(
            db, execution.id, output_format.value
        )

        if existing is not None:
            if existing.checksum != computed:
                raise ConflictException(
                    "A different artifact already exists for this execution "
                    "and format.",
                    code="ARTIFACT_ALREADY_EXISTS",
                )

            return existing, False

        mime_type = MIME_BY_FORMAT.get(
            output_format, "application/octet-stream"
        )

        reference = await get_storage_backend().put(
            db,
            organization_id=execution.organization_id,
            data=data,
            content_type=mime_type,
        )

        artifact = ReportArtifact(
            organization_id=execution.organization_id,
            report_execution_id=execution.id,
            output_format=output_format.value,
            # Server-generated, not worker-supplied: this string ends up
            # in a Content-Disposition header, so it must not be able to
            # carry a newline, a quote, or a path.
            filename=self._artifact_filename(execution, output_format, filename),
            mime_type=mime_type,
            size_bytes=len(data),
            checksum=computed,
            storage_reference=reference,
        )

        artifact = await report_artifact_repository.create(db, artifact)

        return artifact, True

    async def list_for_execution(
        self,
        db: AsyncSession,
        execution: ReportExecution,
    ) -> list[ReportArtifact]:

        return await report_artifact_repository.list_by_execution(
            db, execution.id
        )

    async def get_artifact(
        self,
        db: AsyncSession,
        artifact_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ReportArtifact:

        artifact = await report_artifact_repository.get_by_id(db, artifact_id)

        if artifact is None or artifact.organization_id != organization_id:
            raise NotFoundException("Artifact not found.")

        return artifact

    async def get_content(
        self,
        db: AsyncSession,
        artifact: ReportArtifact,
    ) -> bytes:

        data = await get_storage_backend().get(
            db,
            organization_id=artifact.organization_id,
            reference=artifact.storage_reference,
        )

        if checksum(data) != artifact.checksum:
            raise ConflictException(
                "The stored artifact failed its integrity check and was not "
                "served.",
                code="ARTIFACT_CHECKSUM_MISMATCH",
            )

        return data

    @staticmethod
    def _artifact_filename(
        execution: ReportExecution,
        output_format: OutputFormat,
        suggested: str,
    ) -> str:
        """Build the download name from data we control.

        The worker's suggestion is reduced to an alphanumeric stem and
        capped; the extension comes from the format enum. Nothing the
        worker sends can introduce a separator, a control character, or a
        second extension.
        """

        stem = "".join(
            char
            for char in (suggested or "report").rsplit(".", 1)[0]
            if char.isalnum() or char in {"-", "_"}
        )[:60]

        if not stem:
            stem = "report"

        short_id = str(execution.id)[:8]

        return f"{stem}-{short_id}.{output_format.value}"


artifact_service = ArtifactService()
