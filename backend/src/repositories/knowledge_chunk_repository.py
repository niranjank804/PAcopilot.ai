import uuid

from sqlalchemy import func, select
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

    async def search_by_keyword(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        query: str,
        limit: int,
    ) -> list[tuple[KnowledgeChunk, float]]:
        """Full-text matches for a query, best first, with their rank.

        `websearch_to_tsquery`, not `to_tsquery`: this takes raw text a
        user typed. `to_tsquery` demands operators between terms and
        raises a syntax error on "emea variance" — so the obvious choice
        turns an ordinary question into a 500. `websearch_to_tsquery`
        parses the way a search box does, and treats stray quotes and
        `or` as intent rather than as a parse failure.

        Ranking is `ts_rank`, which is not on the same scale as cosine
        similarity and must not be compared against it — see
        `retrieval.KEYWORD_MINIMUM_SCORE`.
        """

        tsquery = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank(KnowledgeChunk.search_vector, tsquery)

        result = await db.execute(
            select(KnowledgeChunk, rank.label("rank"))
            .where(
                KnowledgeChunk.organization_id == organization_id,
                KnowledgeChunk.search_vector.op("@@")(tsquery),
            )
            .options(selectinload(KnowledgeChunk.document))
            .order_by(rank.desc())
            .limit(limit)
        )

        return [(row[0], float(row[1])) for row in result.all()]

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
