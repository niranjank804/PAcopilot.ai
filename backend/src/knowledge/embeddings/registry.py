from src.ai.exceptions import AIProviderError
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.embeddings.openai_provider import openai_embedding_provider

EMBEDDING_PROVIDERS: dict[str, EmbeddingProvider] = {
    "openai": openai_embedding_provider,
}


def get_embedding_provider(name: str) -> EmbeddingProvider:
    provider = EMBEDDING_PROVIDERS.get(name)

    if provider is None:
        raise AIProviderError(f"Unknown embedding provider: {name}")

    return provider
