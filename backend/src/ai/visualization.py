import json
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.orchestrator import ai_orchestrator
from src.core.config import settings
from src.core.exceptions import ValidationException
from src.database.models.ai_conversation import AIConversation
from src.repositories.ai_conversation_repository import ai_conversation_repository
from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from src.tm1.services.mdx_table import execute_mdx_table, flat_cells

# The answer's JSON block, fenced as ```json, as plain ```, or not at all.
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"(\{[^{}]*\"mdx\"[^{}]*\})", re.DOTALL)

# The analyst's MDX work is a few quick tool rounds; the faster model does
# it well and keeps the page from waiting on the slowest one.
_PREFERRED_MODEL = "claude-sonnet-5"


class VisualizationResult:

    def __init__(
        self,
        cube_name: str,
        mdx: str,
        cells: dict,
        summary: str,
        table: dict | None = None,
    ):
        self.cube_name = cube_name
        self.mdx = mdx
        self.cells = cells
        self.summary = summary
        self.table = table or {"dimensions": [], "rows": [], "truncated": False}


def _mdx_from_answer(content: str) -> tuple[str | None, str]:
    """(mdx, cube) from the agent's final answer, however it fenced it."""

    for pattern in (_FENCED, _BARE):
        for block in reversed(pattern.findall(content)):
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("mdx"):
                return str(parsed["mdx"]), str(parsed.get("cube_name") or "")

    return None, ""


async def _last_working_mdx(db: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    """The last MDX the agent ran successfully in this conversation.

    The agent proves its query by running it; when its final message then
    forgets the JSON block, the query it proved is still in the tool log.
    """

    executions = await ai_tool_execution_repository.list_by_conversation(
        db, conversation_id
    )

    for execution in reversed(executions):
        mdx = (execution.arguments or {}).get("mdx")
        if execution.tool_name == "execute_mdx" and execution.status == "success" and mdx:
            return str(mdx)

    return None


def _cube_from_mdx(mdx: str) -> str:
    match = re.search(r"\bFROM\s+\[((?:[^\]]|\]\])+)\]", mdx, re.IGNORECASE)
    return match.group(1).replace("]]", "]") if match else ""


async def run_mdx(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    connection_id: uuid.UUID,
    mdx: str,
) -> dict:
    """Run MDX for the page as a table. Read-only: TM1 MDX only selects."""

    connection = await tm1_integration_service.get_connection(
        db, connection_id, organization_id
    )
    client = await tm1_connection_manager.get_client(connection)

    return await execute_mdx_table(client, connection.id, mdx)


async def generate_visualization(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    query: str,
) -> VisualizationResult:
    """Natural language -> MDX -> a table the page can chart any way.

    Reuses the agent tool-calling loop (analyst persona) so the query is
    grounded in real cube, dimension and element names, then re-runs the
    final MDX itself so the page gets the full result rather than the
    truncated tool output.
    """

    prompt = (
        f"Use connection_id={connection_id} for every tool call. "
        f"Visualization request: {query}\n\n"
        "Find the right cube and confirm real element names, then run the "
        "MDX with execute_mdx to prove it works. Put the dimension the user "
        "wants to compare across (usually time) on COLUMNS and a second "
        "breakdown, if they asked for one, on ROWS; put fixed selections in "
        "WHERE. When you're done, respond with one short sentence "
        "summarizing what the data shows, followed by a fenced ```json code "
        'block containing exactly this shape: {"cube_name": "...", "mdx": '
        '"..."} — the mdx must be the exact, final query that already worked '
        "when you ran it."
    )

    # Created up front, already marked, and passed in: the run then never
    # appears in the person's Chat history — not even if it fails midway,
    # which a mark added afterwards would miss.
    conversation = await ai_conversation_repository.create(
        db,
        AIConversation(
            organization_id=organization_id,
            user_id=user_id,
            title=f"Visualize: {query.strip()[:48]}",
            purpose="visualize",
        ),
    )

    chat_result = await ai_orchestrator.chat(
        db,
        organization_id=organization_id,
        user_id=user_id,
        message=prompt,
        conversation_id=conversation.id,
        agent="analyst",
        model=(
            _PREFERRED_MODEL
            if _PREFERRED_MODEL in settings.AI_ALLOWED_MODELS
            else None
        ),
    )

    mdx, cube_name = _mdx_from_answer(chat_result.content)

    if not mdx:
        mdx = await _last_working_mdx(db, chat_result.conversation_id)

    if not mdx:
        raise ValidationException(
            "The analyst couldn't find data for this question. Name the cube "
            "or measure, and a period — for example 'Revenue by month for "
            "2026 in the Sales cube'."
        )

    table = await run_mdx(
        db, organization_id=organization_id, connection_id=connection_id, mdx=mdx
    )

    summary = chat_result.content.split("```")[0].strip()

    return VisualizationResult(
        cube_name=cube_name or _cube_from_mdx(mdx),
        mdx=mdx,
        cells=flat_cells(table),
        summary=summary or f"Results for: {query}",
        table=table,
    )
