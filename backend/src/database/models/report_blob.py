import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportBlob(BaseModel, OrganizationScoped):
    """Binary content for workbooks and generated artifacts.

    Separate from the metadata tables on purpose: metadata is listed,
    filtered and joined constantly, and a bytea column on those tables
    would be pulled into memory by every `SELECT *`-shaped ORM load.
    Referenced only through `src/reports/storage.py`.
    """

    __tablename__ = "report_blobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    content: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
