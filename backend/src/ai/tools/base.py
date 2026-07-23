import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.schemas import ToolDefinition

CODE_TRUNCATION_LIMIT = 6000


def truncate_code(text: str, limit: int = CODE_TRUNCATION_LIMIT) -> str:
    """Cap code/rule text fed into the LLM context; the API returns it untruncated."""

    if len(text) <= limit:
        return text

    return text[:limit] + "\n[truncated]"


class Tool(ABC):

    name: str
    description: str
    input_schema: dict
    required_permission: str | None = None

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    @abstractmethod
    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:
        ...
