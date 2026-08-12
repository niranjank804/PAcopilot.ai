import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportArtifact(BaseModel, OrganizationScoped):
    """A file produced by one execution.

    `storage_reference` never leaves the server. Downloads go through an
    authenticated route that re-checks permission and organization on
    every request, so an artifact id is an identifier and not a bearer
    token — a link that leaks cannot be replayed by someone else.

    The unique constraint on (execution, format) is the second half of
    duplicate suppression: a worker that retries its upload after a
    network blip must not create a second artifact row for the same
    output.
    """

    __tablename__ = "report_artifacts"

    __table_args__ = (
        UniqueConstraint(
            "report_execution_id",
            "output_format",
            name="uq_report_artifacts_execution_format",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    report_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    output_format: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    storage_reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
