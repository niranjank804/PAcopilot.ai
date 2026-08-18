"""What a visual embedding provider must do.

Deliberately multi-vector at the interface, returning a matrix per page
rather than a vector. A single-vector provider expresses itself as a
1xD matrix and loses nothing; a multi-vector provider forced through a
single-vector interface has to mean-pool, which throws away exactly the
information late interaction exists to use. The lossy direction is the
one that must be the caller's choice, so the interface is the general
shape.

`availability()` is part of the contract rather than an afterthought.
ColPali is a 3B-parameter model that cannot load in a 512MB container,
so "can this run here?" is a real, deployment-dependent question, and
the honest answer has to reach the user as an explanation rather than
as an ImportError or an OOM kill.
"""

import uuid
from abc import ABC, abstractmethod

import numpy as np

from src.knowledge.visual.rasterize import RenderedPage


class Availability:

    def __init__(self, available: bool, reason: str):
        self.available = available
        # Read by a user, not only a log: it is the text shown when
        # visual search cannot answer, so it should say what is missing
        # and what would fix it.
        self.reason = reason


class VisualEmbeddingProvider(ABC):

    #: Persisted with every page, so a later change of provider is
    #: detectable rather than silently mixing incomparable vector spaces
    #: in one ranking.
    name: str

    @abstractmethod
    def availability(self) -> Availability:
        ...

    @abstractmethod
    async def embed_pages(
        self,
        pages: list[RenderedPage],
        *,
        organization_id: uuid.UUID,
    ) -> list[np.ndarray]:
        """One (vectors, dimensions) matrix per page, in page order."""

    @abstractmethod
    async def embed_query(self, query: str) -> np.ndarray:
        """A (vectors, dimensions) matrix for the query.

        Must live in the same vector space as `embed_pages`. For
        ColPali that means the query goes through the same model; for a
        text proxy, the same text embedding model.
        """
