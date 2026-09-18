from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderRateLimitError,
)
from src.core.config import settings
from src.knowledge.embeddings.base import EmbeddingProvider

if TYPE_CHECKING:
    import openai


def _openai():
    """The SDK, imported on first use — see _anthropic() in the chat
    provider for why."""

    import openai as sdk

    return sdk


class OpenAIEmbeddingProvider(EmbeddingProvider):

    def __init__(self):
        self._client: openai.AsyncOpenAI | None = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            try:
                self._client = _openai().AsyncOpenAI(
                    api_key=settings.OPENAI_API_KEY,
                )
            except _openai().OpenAIError as exc:
                raise AIProviderAuthenticationError(str(exc)) from exc

        return self._client

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        try:
            response = await self.client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
            )
        except _openai().RateLimitError as exc:
            raise AIProviderRateLimitError(str(exc)) from exc
        except _openai().AuthenticationError as exc:
            raise AIProviderAuthenticationError(str(exc)) from exc
        except (_openai().APIStatusError, _openai().APIConnectionError) as exc:
            raise AIProviderError(str(exc)) from exc

        return [item.embedding for item in response.data]


openai_embedding_provider = OpenAIEmbeddingProvider()
