"""Retrieve on page text; answer from the page image.

The honest description of this provider is that it does half of visual
RAG, and it is the half that runs on the deployment this product
actually has. ColPali needs a GPU and ~6GB of weights; a free Render
container has 512MB and no GPU, so `colpali` cannot be the default and
pretending otherwise would produce a feature that 500s on first use.

What splitting the pipeline buys: retrieval picks pages by their
extracted text, exactly as the existing chunk search does, but what is
sent to the model is the *rendered page*. So a question whose answer
lives in a chart is still answered correctly whenever the surrounding
text is enough to find the page — Claude reads the chart directly
instead of receiving pypdf's rendering of it, which is a column of
numbers with the axis labels gone.

What it does not buy: finding a page whose answer is *only* visual — an
unlabelled trend line, a figure with no caption. Locating those is what
ColPali is for, and the interface is shared so switching costs a
setting and a re-index.

One vector per page, so MaxSim reduces exactly to cosine similarity.
That is not a special case in the scoring code; it is what late
interaction with a single token already means.
"""

import uuid

import numpy as np

from src.core.config import settings
from src.knowledge.embeddings.registry import get_embedding_provider
from src.knowledge.visual.late_interaction import as_array
from src.knowledge.visual.providers.base import Availability, VisualEmbeddingProvider
from src.knowledge.visual.rasterize import RenderedPage

# A page that rendered but yielded almost no text is a scan or a
# full-page figure. Embedding the handful of characters it did produce
# would place it somewhere arbitrary in the vector space and let it
# surface for unrelated queries, so it is stored (the image is still
# worth having) with no embedding, and simply never retrieved by this
# provider. ColPali is what makes such a page findable.
MINIMUM_TEXT_CHARACTERS = 40


class TextProxyVisualProvider(VisualEmbeddingProvider):

    name = "text-proxy"

    def availability(self) -> Availability:
        if not settings.OPENAI_API_KEY:
            return Availability(
                False,
                "Visual search needs the text embedding provider, and "
                "OPENAI_API_KEY is not configured.",
            )

        return Availability(True, "Ready.")

    async def embed_pages(
        self,
        pages: list[RenderedPage],
        *,
        organization_id: uuid.UUID,
    ) -> list[np.ndarray]:
        provider = get_embedding_provider("openai")

        # Empty matrices for text-poor pages, without spending an API
        # call on them. Indices are tracked so the results can be put
        # back in page order.
        indexed = [
            (index, page)
            for index, page in enumerate(pages)
            if len(page.text) >= MINIMUM_TEXT_CHARACTERS
        ]

        embeddings: list[np.ndarray] = [
            np.zeros((0, 0), dtype=np.float32) for _ in pages
        ]

        if not indexed:
            return embeddings

        vectors = await provider.embed([page.text for _, page in indexed])

        for (index, _), vector in zip(indexed, vectors):
            embeddings[index] = as_array(vector)

        return embeddings

    async def embed_query(self, query: str) -> np.ndarray:
        provider = get_embedding_provider("openai")

        [vector] = await provider.embed([query])

        return as_array(vector)


text_proxy_visual_provider = TextProxyVisualProvider()
