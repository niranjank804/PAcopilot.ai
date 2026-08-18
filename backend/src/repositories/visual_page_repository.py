import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import defer, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.visual_page import VisualPage


class VisualPageRepository:

    async def list_for_scoring(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        embedding_model: str,
    ) -> list[VisualPage]:
        """Pages that can be ranked: this organization, this provider.

        Filtering on the model is not an optimisation. Vectors from
        different providers occupy different spaces, so ranking a
        ColPali page against a text-proxy page compares numbers that
        have no relationship, and whichever happens to score higher
        wins for no reason.

        `text` is deferred because scoring never reads it and a page of
        extracted text is a few KB — over a few thousand pages that is
        megabytes pulled through the connection for nothing. The
        embedding blob is loaded, since it is the thing being scored.
        """

        result = await db.execute(
            select(VisualPage)
            .where(
                VisualPage.organization_id == organization_id,
                VisualPage.embedding_model == embedding_model,
                VisualPage.embedding.is_not(None),
            )
            .options(defer(VisualPage.text), selectinload(VisualPage.document))
        )

        return list(result.scalars().all())

    async def list_by_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> list[VisualPage]:

        result = await db.execute(
            select(VisualPage)
            .where(VisualPage.document_id == document_id)
            .order_by(VisualPage.page_number)
            .options(defer(VisualPage.embedding))
        )

        return list(result.scalars().all())

    async def get_by_id(
        self,
        db: AsyncSession,
        page_id: uuid.UUID,
    ) -> VisualPage | None:

        result = await db.execute(select(VisualPage).where(VisualPage.id == page_id))

        return result.scalars().first()

    async def delete_for_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> list[str]:
        """Remove a document's pages, returning their image references.

        The references come back so the caller can delete the objects
        too: rows are what CASCADE handles, but an S3 object outlives
        its row forever unless something removes it, and orphaned
        objects are billed.
        """

        existing = await db.execute(
            select(VisualPage.image_reference).where(
                VisualPage.document_id == document_id
            )
        )
        references = [row[0] for row in existing]

        await db.execute(delete(VisualPage).where(VisualPage.document_id == document_id))

        return references

    async def create(self, db: AsyncSession, page: VisualPage) -> VisualPage:
        db.add(page)

        await db.flush()

        return page


visual_page_repository = VisualPageRepository()
