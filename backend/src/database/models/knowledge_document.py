import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class KnowledgeDocument(BaseModel, OrganizationScoped):
    __tablename__ = "knowledge_documents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
    )

    # Why visual indexing did not happen, when text indexing did. Kept
    # separate from `error_message` because the document is not failed:
    # it is searchable by text and simply has no page images, and
    # merging the two would make a fully-working document report as
    # broken.
    visual_index_error: Mapped[str | None] = mapped_column(
        Text,
    )

    visual_pages = relationship(
        "VisualPage",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )
