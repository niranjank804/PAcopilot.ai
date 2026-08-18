"""Provider selection, mirroring src/knowledge/embeddings/registry.py."""

from src.ai.exceptions import AIProviderError
from src.core.config import settings
from src.knowledge.visual.providers.base import Availability, VisualEmbeddingProvider
from src.knowledge.visual.providers.colpali_local import colpali_visual_provider
from src.knowledge.visual.providers.text_proxy import text_proxy_visual_provider

VISUAL_PROVIDERS: dict[str, VisualEmbeddingProvider] = {
    "text-proxy": text_proxy_visual_provider,
    "colpali": colpali_visual_provider,
}


def get_visual_provider(name: str | None = None) -> VisualEmbeddingProvider:
    resolved = name or settings.VISUAL_RAG_PROVIDER
    provider = VISUAL_PROVIDERS.get(resolved)

    if provider is None:
        known = ", ".join(sorted(VISUAL_PROVIDERS))

        raise AIProviderError(
            f"Unknown visual embedding provider: {resolved}. Known: {known}."
        )

    return provider


def visual_rag_availability() -> Availability:
    """Whether visual search can run, and what to do if not.

    Checked before an upload is accepted for visual indexing and before
    a visual search runs, so a missing GPU or an unconfigured key
    becomes a sentence the user can act on rather than a stack trace.
    """

    if not settings.VISUAL_RAG_ENABLED:
        return Availability(False, "Visual search is disabled on this deployment.")

    return get_visual_provider().availability()
