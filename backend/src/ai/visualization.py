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


# How many of the agent's own queries to re-run, newest first, looking for
# one that returns data.
_MAX_FALLBACK_QUERIES = 5


async def _ran_mdx(db: AsyncSession, conversation_id: uuid.UUID) -> list[str]:
    """The MDX the agent ran successfully in this conversation, newest first.

    The agent proves its query by running it; when its final message then
    leaves out the JSON block, the queries it ran are still in the tool
    log. Newest first but not only the newest: an agent often ends on an
    exploratory query that came back empty after an earlier one that
    returned exactly the data asked for.
    """

    executions = await ai_tool_execution_repository.list_by_conversation(
        db, conversation_id
    )

    queries: list[str] = []
    for execution in reversed(executions):
        if execution.status != "success":
            continue
        if execution.tool_name in ("execute_mdx", "show_chart"):
            mdx = (execution.arguments or {}).get("mdx")
        elif execution.tool_name == "query_cube":
            # query_cube builds its MDX; its result starts with it.
            mdx = _mdx_from_query_cube(execution.result_summary or "")
        else:
            continue
        if mdx and str(mdx) not in queries:
            queries.append(str(mdx))

    return queries


_QUERY_CUBE_MDX = re.compile(r'^\{"mdx":\s*("(?:[^"\\]|\\.)*")')


def _mdx_from_query_cube(summary: str) -> str | None:
    """The MDX at the start of a query_cube result, if it was not cut off
    by the 500-character summary."""

    match = _QUERY_CUBE_MDX.match(summary)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
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
        "Steps: find the right cube (list_cubes, get_cube). Call find_data "
        "on it with the members the request names as filters (the account "
        "or measure, a version or year). Then call query_cube with the "
        "dimension to compare across (usually time) as columns, the "
        "breakdown asked for as rows, and find_data's where_with_data as "
        "filters. Do not write MDX by hand, and do not call show_chart: "
        "this page draws the chart from your query. If find_data says "
        "found: false, say there is no data for that selection.\n\n"
        "If part of the request has no data (for example Actual is empty "
        "for a future year, or the model calls Budget 'Plan'), do not give "
        "up: use the query that does return data and say in the summary "
        "what is missing and why.\n\n"
        "When you're done, respond with at most three short sentences on "
        "what the data shows (and anything missing), followed by a fenced "
        '```json code block containing exactly this shape: {"cube_name": '
        '"...", "mdx": "..."} — the mdx must be the exact query query_cube '
        "returned and that returned data. Always include the block when any "
        "query returned data."
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

    answered, cube_name = _mdx_from_answer(chat_result.content)

    # The query the answer names, then the agent's own queries newest
    # first; the first that returns data is the one shown. If none does,
    # the first is shown empty, with its MDX to edit.
    candidates = [answered] if answered else []
    for ran in await _ran_mdx(db, chat_result.conversation_id):
        if ran not in candidates:
            candidates.append(ran)
    candidates = candidates[:_MAX_FALLBACK_QUERIES]

    if not candidates:
        raise ValidationException(
            "The analyst couldn't find data for this question. Name the cube "
            "or measure, and a period — for example 'Revenue by month for "
            "2026 in the Sales cube'."
        )

    mdx, table = candidates[0], None
    for candidate in candidates:
        result = await run_mdx(
            db,
            organization_id=organization_id,
            connection_id=connection_id,
            mdx=candidate,
        )
        if table is None:
            table = result
        if result["rows"]:
            mdx, table = candidate, result
            break

    if mdx != answered:
        cube_name = ""

    summary = chat_result.content.split("```")[0].strip()

    return VisualizationResult(
        cube_name=cube_name or _cube_from_mdx(mdx),
        mdx=mdx,
        cells=flat_cells(table),
        summary=summary or f"Results for: {query}",
        table=table,
    )
