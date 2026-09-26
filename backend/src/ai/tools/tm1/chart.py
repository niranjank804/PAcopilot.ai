import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from src.tm1.services.mdx_table import execute_mdx_table

# Rows the model reads back, to explain the chart. The person sees every
# row: the chat page re-runs the query for the chart itself.
_PREVIEW_ROWS = 40

VISUALS = [
    "column",
    "bar",
    "stacked",
    "stacked100",
    "line",
    "area",
    "pie",
    "donut",
    "treemap",
    "heatmap",
    "waterfall",
    "kpi",
    "matrix",
]


class ShowChartTool(Tool):

    name = "show_chart"
    description = (
        "Show the person a chart of an MDX query's result, inside the chat. "
        "Call it when they ask to see, chart, plot, graph, visualize or "
        "compare data — after execute_mdx has confirmed the query returns "
        "data. Put the dimension to compare across (usually time) on "
        "COLUMNS, a second breakdown on ROWS, fixed selections in WHERE. "
        "Returns the dimensions and the first rows so you can explain what "
        "the chart shows; the person sees the full chart and can change "
        "its type, axis and filters."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "mdx": {
                "type": "string",
                "description": "The MDX query to chart — one that already returned data.",
            },
            "title": {
                "type": "string",
                "description": "A short chart title, e.g. 'Revenue by month, 2026'.",
            },
            "visual": {
                "type": "string",
                "enum": VISUALS,
                "description": (
                    "The chart type to open with: line or area for trends "
                    "over time, column or bar to compare categories, pie or "
                    "donut for shares of a whole (few slices), matrix for a "
                    "table. The person can change it."
                ),
            },
        },
        "required": ["connection_id", "mdx", "title"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )

        connection = await tm1_integration_service.get_connection(
            db, uuid.UUID(str(kwargs["connection_id"])), organization_id
        )
        client = await tm1_connection_manager.get_client(connection)
        table = await execute_mdx_table(client, connection.id, str(kwargs["mdx"]))

        if not table["rows"]:
            return json.dumps(
                {
                    "shown": False,
                    "reason": (
                        "The query returned no cells, so no chart was shown. "
                        "Check the element names or try another period."
                    ),
                }
            )

        return json.dumps(
            {
                "shown": True,
                "title": kwargs.get("title") or "",
                "cell_count": len(table["rows"]),
                "truncated": table["truncated"],
                "dimensions": table["dimensions"],
                "rows": table["rows"][:_PREVIEW_ROWS],
            },
            default=str,
        )
