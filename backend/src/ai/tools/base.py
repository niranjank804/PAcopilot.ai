import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.schemas import ToolDefinition
from src.ai.tools.classification import ToolClassification, classification_for

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

    @property
    def classification(self) -> ToolClassification:
        """Category, access class and evidence source. Every registered
        tool has one; tests/unit/ai/test_tool_classification.py enforces it."""

        found = classification_for(self.name)

        if found is None:
            raise LookupError(f"Tool {self.name!r} is not classified.")

        return found

    def describe_target(self, arguments: dict) -> str:
        """The object this call acts on, for the timeline and the audit row.

        Built from the classified target inputs only, so a long argument
        (MDX, process code) never lands in a label.
        """

        parts = [
            str(arguments[key])[:120]
            for key in self.classification.target_keys
            if arguments.get(key) not in (None, "")
        ]

        return " / ".join(parts)

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
