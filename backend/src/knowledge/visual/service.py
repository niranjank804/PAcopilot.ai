"""Indexing and searching document pages as images.

The pipeline, end to end:

    PDF -> rasterize -> store image -> embed page -> visual_pages row
    query -> embed -> MaxSim over pages -> top-k page images -> Claude

The last arrow is the point. Retrieval finds *pages*, and what is handed
to the model is the rendered page rather than extracted text, so a
figure, a pivot table or a chart is read as what it is. Ordinary
chunk-based RAG hands over pypdf's serialisation of a table, which is a
column of numbers with the row and column headings that gave them
meaning discarded.

Page images go through `StorageBackend`, so they land in S3 when a
bucket is configured and in Postgres otherwise — and the tenant-prefix
check in the S3 backend applies to them unchanged.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import app_logger
from src.database.models.knowledge_document import KnowledgeDocument
from src.database.models.visual_page import VisualPage
from src.knowledge.exceptions import KnowledgeServiceError
from src.knowledge.visual import codec
from src.knowledge.visual.late_interaction import maxsim
from src.knowledge.visual.providers.registry import (
    get_visual_provider,
    visual_rag_availability,
)
from src.knowledge.visual.rasterize import RasterizationError, rasterize_pdf
from src.reports.storage import get_storage_backend
from src.repositories.visual_page_repository import visual_page_repository


class PageMatch:

    def __init__(self, page: VisualPage, score: float):
        self.page = page
        self.score = score


class VisualIndexResult:

    def __init__(self, pages_indexed: int, pages_embedded: int, provider: str):
        self.pages_indexed = pages_indexed
        # Deliberately distinct from pages_indexed. Under the text-proxy
        # provider a scanned page renders and is stored but produces no
        # embedding, so it is not retrievable — reporting only the
        # stored count would imply a searchability the index does not
        # have.
        self.pages_embedded = pages_embedded
        self.provider = provider


class VisualService:

    async def index_document(
        self,
        db: AsyncSession,
        *,
        document: KnowledgeDocument,
        organization_id: uuid.UUID,
        file_bytes: bytes,
    ) -> VisualIndexResult:

        availability = visual_rag_availability()

        if not availability.available:
            raise KnowledgeServiceError(availability.reason)

        provider = get_visual_provider()
        storage = get_storage_backend()

        try:
            pages = await rasterize_pdf(file_bytes)
        except RasterizationError as exc:
            raise KnowledgeServiceError(str(exc)) from exc

        # Re-indexing replaces. Without this a second index of the same
        # document would hit the (document_id, page_number) unique
        # constraint, and without the constraint it would quietly double
        # every page and let the copies compete for retrieval slots.
        stale_references = await visual_page_repository.delete_for_document(
            db, document.id
        )

        embeddings = await provider.embed_pages(
            pages, organization_id=organization_id
        )

        embedded = 0

        for page, matrix in zip(pages, embeddings):
            reference = await storage.put(
                db,
                organization_id=organization_id,
                data=page.image_bytes,
                content_type=page.media_type,
            )

            blob = vectors = dimensions = None

            if matrix.size:
                blob, vectors, dimensions = codec.pack(matrix)
                embedded += 1

            await visual_page_repository.create(
                db,
                VisualPage(
                    document_id=document.id,
                    organization_id=organization_id,
                    page_number=page.page_number,
                    image_reference=reference,
                    width=page.width,
                    height=page.height,
                    text=page.text,
                    embedding=blob,
                    embedding_vectors=vectors,
                    embedding_dimensions=dimensions,
                    embedding_model=provider.name,
                ),
            )

        # After the new rows are written, not before: if indexing fails
        # halfway the transaction rolls the rows back, and deleting the
        # objects first would have left the restored rows pointing at
        # images that no longer exist.
        for reference in stale_references:
            await storage.delete(
                db, organization_id=organization_id, reference=reference
            )

        return VisualIndexResult(len(pages), embedded, provider.name)

    async def search(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        query: str,
        top_k: int | None = None,
        minimum_score: float | None = None,
    ) -> list[PageMatch]:
        """Rank an organization's pages by late interaction.

        An exact scan, not an approximate index. Every page is scored,
        which is honest about its cost: it is linear in the page count,
        and the existing text retrieval already scans the same way in
        slower pure Python. For a tenant with tens of thousands of pages
        this becomes the thing to replace — with pgvector's multi-vector
        support, or a two-stage candidate-then-rerank — and the
        interface here does not change when it is.
        """

        availability = visual_rag_availability()

        if not availability.available:
            raise KnowledgeServiceError(availability.reason)

        provider = get_visual_provider()

        top_k = top_k if top_k is not None else settings.VISUAL_RAG_TOP_K
        minimum_score = (
            minimum_score
            if minimum_score is not None
            else settings.VISUAL_RAG_MINIMUM_SCORE
        )

        try:
            query_matrix = await provider.embed_query(query)
        except Exception as exc:
            raise KnowledgeServiceError(
                "Visual search is unavailable — the embedding provider "
                "isn't configured or reachable. Contact your administrator."
            ) from exc

        pages = await visual_page_repository.list_for_scoring(
            db, organization_id, provider.name
        )

        matches: list[PageMatch] = []

        for page in pages:
            try:
                page_matrix = codec.unpack(
                    page.embedding,
                    page.embedding_vectors,
                    page.embedding_dimensions,
                )
            except codec.EmbeddingShapeError as exc:
                # One damaged row must not take down every search. It is
                # logged with its id so it can be re-indexed, and skipped.
                app_logger.warning(
                    f"visual rag: unreadable embedding on page {page.id}: {exc}"
                )
                continue

            if page_matrix.shape[1] != query_matrix.shape[1]:
                # Same provider name, different dimensions — the model
                # changed under a stable name. Scoring anyway would
                # raise deep inside numpy on a shape mismatch.
                continue

            score = maxsim(query_matrix, page_matrix)

            if score >= minimum_score:
                matches.append(PageMatch(page, score))

        matches.sort(key=lambda match: match.score, reverse=True)

        return matches[:top_k]

    async def load_image(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        page: VisualPage,
    ) -> bytes:
        """Fetch a page image, tenant-checked by the storage backend."""

        storage = get_storage_backend()

        return await storage.get(
            db,
            organization_id=organization_id,
            reference=page.image_reference,
        )

    async def delete_for_document(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> None:
        """Drop a document's pages and their stored images."""

        storage = get_storage_backend()

        references = await visual_page_repository.delete_for_document(db, document_id)

        for reference in references:
            await storage.delete(
                db, organization_id=organization_id, reference=reference
            )


visual_service = VisualService()
