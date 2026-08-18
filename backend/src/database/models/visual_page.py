import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class VisualPage(BaseModel, OrganizationScoped):
    """One rendered page of a document, with its visual embedding.

    Hangs off `knowledge_documents` rather than introducing a parallel
    document table: a page image is another representation of a file
    the organization already uploaded, so upload, deduplication,
    permissions and tenancy stay in one place, and deleting the
    document takes its pages with it.
    """

    __tablename__ = "visual_pages"

    __table_args__ = (
        # Re-indexing a document must replace its pages, not accumulate
        # a second set that then competes with the first for retrieval
        # slots. The reference implementation keyed on Python's hash(),
        # which is salted per process, so re-ingesting the same PDF
        # produced fresh ids and silently duplicated every page.
        UniqueConstraint("document_id", "page_number", name="uq_visual_page_document_page"),
        # The retrieval scan is always "this organization's pages that
        # have an embedding". Without this it is a sequential scan over
        # every tenant's pages, each row carrying a ~257KB blob.
        Index("ix_visual_pages_org_model", "organization_id", "embedding_model"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1-based, matching what a reader sees in a PDF viewer, so a
    # citation never needs a +1 applied in one place and forgotten in
    # another.
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # A StorageBackend reference (`s3://...` or `db://...`), not the
    # bytes. Page images are ~200KB each and a 100-page document would
    # otherwise put 20MB of binary into a 500MB free Postgres — which is
    # the problem the S3 backend was built to solve.
    image_reference: Mapped[str] = mapped_column(String(500), nullable=False)

    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)

    # Kept for the text-proxy provider, for keyword fallback, and so a
    # citation can show a snippet without fetching the image.
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # float16 matrix, see src/knowledge/visual/codec.py. Nullable
    # because a page that rendered but yielded no usable text has no
    # embedding under the text-proxy provider — the image is still worth
    # storing, the page simply is not retrievable until re-indexed with
    # a provider that can see it.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Shape stored explicitly: a flat blob cannot say whether it is
    # 1030x128 or 128x1030, and guessing transposes it into nonsense.
    embedding_vectors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which provider produced it. Vectors from different providers are
    # not comparable, so retrieval filters on this rather than ranking
    # across two incompatible spaces.
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)

    document = relationship("KnowledgeDocument", back_populates="visual_pages")
