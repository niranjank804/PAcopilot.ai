import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportWorkbook(BaseModel, OrganizationScoped):
    """A PAfE workbook held in custody, not a URL.

    `storage_reference` is an internal locator resolved by
    `src/reports/storage.py`; it is never serialized to a client. Content
    is fetched through an authenticated, org-checked API route so that
    possession of an identifier is not itself an authorization.

    `checksum` is the contract between this table and the worker: the
    worker recomputes SHA-256 after download and refuses to open a
    workbook whose bytes changed in transit or at rest.

    `version` increments when new content is uploaded under the same
    logical workbook. Old versions are separate rows, so an execution
    that ran last month still points at the bytes it actually used.
    """

    __tablename__ = "report_workbooks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    # Sanitized at upload — see src/reports/validation.py. The worker does
    # NOT use this to name the file it writes to disk.
    filename: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    storage_reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )

    # Host requirements observed for this workbook (e.g. minimum PAfE
    # version, whether macros are required). Populated by the worker after
    # a successful run; advisory, never a substitute for the capability
    # check performed at assignment time.
    compatibility: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
