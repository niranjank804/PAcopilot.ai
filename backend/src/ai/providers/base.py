from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.ai.schemas import ChatRequest, ChatResponse, StreamEvent


class AIProvider(ABC):

    @abstractmethod
    async def chat(
        self,
        request: ChatRequest,
    ) -> ChatResponse:
        ...

    @abstractmethod
    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[StreamEvent]:
        ...

    @abstractmethod
    async def count_tokens(
        self,
        request: ChatRequest,
    ) -> int:
        ...
