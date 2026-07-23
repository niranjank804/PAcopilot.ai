from src.ai.exceptions import AIProviderError
from src.ai.providers.anthropic_provider import anthropic_provider
from src.ai.providers.base import AIProvider

PROVIDERS: dict[str, AIProvider] = {
    "anthropic": anthropic_provider,
}


def get_provider(name: str) -> AIProvider:
    provider = PROVIDERS.get(name)

    if provider is None:
        raise AIProviderError(f"Unknown AI provider: {name}")

    return provider
