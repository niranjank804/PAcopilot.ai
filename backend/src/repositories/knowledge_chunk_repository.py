import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models.knowledge_chunk import KnowledgeChunk


class KnowledgeChunkRepository:

    async def list_by_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[KnowledgeChunk]:

        result = await db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.organization_id == organization_id)
            .options(selectinload(KnowledgeChunk.document))
        )

        return list(result.scalars().all())

    async def list_by_document(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
    ) -> list[KnowledgeChunk]:

        result = await db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
        )

        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        chunk: KnowledgeChunk,
    ) -> KnowledgeChunk:

        db.add(chunk)

        await db.flush()

        await db.refresh(chunk)

        return chunk


knowledge_chunk_repository = KnowledgeChunkRepository()
