import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.knowledge_chunk import KnowledgeChunk
from src.repositories.knowledge_chunk_repository import knowledge_chunk_repository


class ChunkMatch:

    def __init__(self, chunk: KnowledgeChunk, score: float):
        self.chunk = chunk
        self.score = score


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))

    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


async def search(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[ChunkMatch]:

    chunks = await knowledge_chunk_repository.list_by_organization(
        db,
        organization_id,
    )

    matches = [
        ChunkMatch(chunk, cosine_similarity(query_embedding, chunk.embedding))
        for chunk in chunks
    ]

    matches.sort(key=lambda match: match.score, reverse=True)

    return matches[:top_k]
