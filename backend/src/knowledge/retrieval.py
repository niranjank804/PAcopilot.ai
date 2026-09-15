import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.knowledge_chunk import KnowledgeChunk
from src.repositories.knowledge_chunk_repository import knowledge_chunk_repository


#: How a match was found. Carried on every result because the two modes
#: are not interchangeable in quality *or* in score scale, and a caller
#: that cannot tell them apart will eventually compare them.
SEMANTIC = "semantic"
KEYWORD = "keyword"


class SearchOutcome(list):
    """The matches, plus how they were found.

    A list subclass rather than a wrapper object, so that the six
    existing call sites — including the `search_knowledge_base` AI tool —
    keep treating the result as the list it has always been, while
    callers that care can read `.mode`.

    The mode has to live here rather than being read off the first
    match, because the case that matters most is the empty one: when the
    embedding provider is down *and* keyword search finds nothing, the
    answer must still be able to say the search was degraded. Inferring
    from `matches[0]` would report a confident "semantic" for exactly
    that situation.
    """

    def __init__(self, matches=(), *, mode: str = SEMANTIC):
        super().__init__(matches)
        self.mode = mode


class ChunkMatch:

    def __init__(
        self,
        chunk: KnowledgeChunk,
        score: float,
        mode: str = SEMANTIC,
    ):
        self.chunk = chunk
        self.score = score
        # Defaults to SEMANTIC so the embedding path reads unchanged;
        # only the fallback has to say what it is.
        self.mode = mode


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
) -> SearchOutcome:
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

    return SearchOutcome(matches[:top_k], mode=SEMANTIC)


# `ts_rank` is not a similarity. It is an unbounded relevance weight
# derived from term frequency and position, so the 0.2 floor above —
# tuned for cosine similarity on text-embedding-3-small — is meaningless
# here. Postgres already answered the only question that matters for
# keyword search, by matching the tsquery at all; this floor exists just
# to drop matches so weak that a single incidental word produced them.
KEYWORD_MINIMUM_SCORE = 1e-6


async def keyword_search(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    top_k: int = 5,
) -> SearchOutcome:
    """Postgres full-text search, for when embeddings are unavailable.

    Deliberately not a silent substitute for semantic search: every
    result carries `mode=KEYWORD` so the answer can say so. It finds a
    chunk that shares words with the question, which is a different and
    weaker thing than finding one that shares meaning — "what drove the
    shortfall?" will not match a passage about "variance" here.

    What it is, is free and unaffected by an external provider's billing.
    """

    rows = await knowledge_chunk_repository.search_by_keyword(
        db, organization_id, query, top_k
    )

    return SearchOutcome(
        (
            ChunkMatch(chunk, rank, mode=KEYWORD)
            for chunk, rank in rows
            if rank >= KEYWORD_MINIMUM_SCORE
        ),
        mode=KEYWORD,
    )
