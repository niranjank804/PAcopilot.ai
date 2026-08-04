import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.knowledge_document import KnowledgeDocument


class KnowledgeDocumentRepository:

    async def get_by_id(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> KnowledgeDocument | None:

        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )

        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[KnowledgeDocument]:

        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.organization_id == organization_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )

        return list(result.scalars().all())

    async def get_by_checksum(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        checksum: str,
    ) -> KnowledgeDocument | None:
        """An organization's successfully-indexed document with this content.

        Only completed documents count: a previous upload that failed to
        process left a row behind but no chunks, so matching it would return
        a document that can never be retrieved.
        """

        result = await db.execute(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.organization_id == organization_id,
                KnowledgeDocument.checksum == checksum,
                KnowledgeDocument.processing_status == "completed",
            )
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
    ) -> KnowledgeDocument:

        db.add(document)

        await db.flush()

        await db.refresh(document)

        return document

    async def update(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
    ) -> KnowledgeDocument:

        await db.flush()
        await db.refresh(document)

        return document

    async def delete(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
    ) -> None:

        await db.delete(document)
        await db.flush()


knowledge_document_repository = KnowledgeDocumentRepository()
