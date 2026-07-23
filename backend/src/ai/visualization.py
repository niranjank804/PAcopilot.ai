import json
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.orchestrator import ai_orchestrator
from src.core.exceptions import ValidationException
from src.tm1.service import tm1_integration_service

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class VisualizationResult:

    def __init__(self, cube_name: str, mdx: str, cells: dict[str, float], summary: str):
        self.cube_name = cube_name
        self.mdx = mdx
        self.cells = cells
        self.summary = summary


async def generate_visualization(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    query: str,
) -> VisualizationResult:
    """Natural language -> MDX -> chart-ready cell data.

    Deliberately reuses the existing agent tool-calling loop (analyst
    persona) instead of a bespoke intent-classification pipeline — the
    agent grounds itself in real cube/dimension/element names via tool
    calls before writing MDX, then this function independently re-executes
    the final MDX it reports so the frontend gets the full, un-truncated
    cellset (tool-execution audit rows are intentionally truncated to 500
    chars and are not a reliable source for chart data).
    """

    prompt = (
        f"Use connection_id={connection_id} for every tool call. "
        f"Visualization request: {query}\n\n"
        "Find the right cube and confirm real element names, then run the "
        "MDX with execute_mdx to prove it works. When you're done, respond "
        "with one short sentence summarizing what the data shows, followed "
        "by a fenced ```json code block containing exactly this shape: "
        '{"cube_name": "...", "mdx": "..."} — the mdx must be the exact, '
        "final query that already worked when you ran it."
    )

    chat_result = await ai_orchestrator.chat(
        db,
        organization_id=organization_id,
        user_id=user_id,
        message=prompt,
        agent="analyst",
    )

    match = _JSON_BLOCK.search(chat_result.content)

    if not match:
        raise ValidationException(
            "The analyst agent didn't return a usable MDX query for this "
            "request. Try rephrasing with a specific cube, period, or "
            "measure."
        )

    try:
        parsed = json.loads(match.group(1))
        mdx = str(parsed["mdx"])
        cube_name = str(parsed.get("cube_name", ""))
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValidationException(
            "The analyst agent returned a malformed MDX response."
        ) from exc

    result = await tm1_integration_service.execute_mdx(
        db, connection_id, organization_id, mdx,
    )

    summary = chat_result.content.split("```")[0].strip()

    return VisualizationResult(
        cube_name=cube_name,
        mdx=mdx,
        cells=result.cells,
        summary=summary or f"Results for: {query}",
    )
