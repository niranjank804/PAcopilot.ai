import uuid

from sqlalchemy import Computed, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class KnowledgeChunk(BaseModel, OrganizationScoped):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge_documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    embedding: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # Maintained by Postgres, never assigned in Python. Backs the keyword
    # fallback used when the embedding provider is unreachable — which
    # until now made the whole Knowledge Base fail on one external
    # dependency.
    #
    # The two-argument `to_tsvector` is required: a generated column
    # needs an IMMUTABLE expression, and the one-argument form is only
    # STABLE because it reads default_text_search_config at runtime.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )

    document = relationship(
        "KnowledgeDocument",
        back_populates="chunks",
    )
