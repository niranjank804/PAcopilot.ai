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


# Cosine similarity below which a chunk is not about the query. Unrelated text
# under text-embedding-3-small sits near zero; genuinely relevant passages are
# comfortably above this. Deliberately low — the aim is to drop noise, not to
# second-guess ranking.
MINIMUM_SCORE = 0.2


async def search(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
    minimum_score: float = MINIMUM_SCORE,
) -> list[ChunkMatch]:
    """Rank an organization's chunks against a query embedding.

    Returning nothing is a valid answer. Without a floor this returned the
    top five chunks whatever they contained, so a question the knowledge base
    could not answer still came back with five confident-looking citations —
    which is how a grounded assistant ends up citing an unrelated document.
    """

    chunks = await knowledge_chunk_repository.list_by_organization(
        db,
        organization_id,
    )

    matches = [
        match
        for chunk in chunks
        if (match := ChunkMatch(chunk, cosine_similarity(query_embedding, chunk.embedding))).score
        >= minimum_score
    ]

    matches.sort(key=lambda match: match.score, reverse=True)

    return matches[:top_k]
