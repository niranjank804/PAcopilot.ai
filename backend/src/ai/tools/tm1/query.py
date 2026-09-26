import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from src.tm1.services.query_builder import (
    LEVELS,
    QuerySpecError,
    find_data,
    query_cube,
)
from src.tm1.services.query_context import cube_query_context


class GetQueryContextTool(Tool):
    name = "get_query_context"
    description = (
        "Before writing MDX against a cube, get what the query must say about "
        "each of its dimensions: the default member, the top-level elements "
        "(usually the totals), and a WHERE clause that pins every dimension "
        "to a total. A dimension left out of a query reads its default "
        "member, which is often a blank or unused element — the usual reason "
        "a query returns no cells. Start from where_all_totals: take the "
        "dimensions you want on the axes out of it and replace the rest with "
        "the specific members asked for (measure, version, period)."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection.",
            },
            "cube_name": {
                "type": "string",
                "description": "The cube the query will read.",
            },
        },
        "required": ["connection_id", "cube_name"],
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

        return json.dumps(
            await cube_query_context(client, connection.id, str(kwargs["cube_name"]))
        )


# How an axis is described to query_cube. One of members / children_of /
# level; with none, the children of the dimension's total ("by department").
_AXIS_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string", "description": "A dimension of the cube."},
        "members": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exactly these elements, e.g. the months of 2026.",
        },
        "children_of": {
            "type": "string",
            "description": "The children of this element, e.g. a year's months.",
        },
        "level": {
            "type": "string",
            "enum": list(LEVELS),
            "description": "leaves, all, or top (the top-level elements).",
        },
    },
    "required": ["dimension"],
}

_FILTERS_SCHEMA = {
    "type": "object",
    "additionalProperties": {"type": "string"},
    "description": (
        "Dimension -> element for the members asked for (the measure or "
        "account, the version, the year). Every other dimension not on an "
        "axis is set to its total automatically."
    ),
}

# Rows the model reads back; the page and show_chart re-run for all of them.
_PREVIEW_ROWS = 40


async def _client_for(db, organization_id, connection_id):
    connection = await tm1_integration_service.get_connection(
        db, uuid.UUID(str(connection_id)), organization_id
    )
    return connection, await tm1_connection_manager.get_client(connection)


async def _require_read(db, user_id, permission):
    if not await auth_repository.user_has_permission(db, user_id, permission):
        raise PermissionDeniedException("You do not have permission to read TM1 data.")


class FindDataTool(Tool):
    name = "find_data"
    description = (
        "Find where a cube holds data before charting it. Checks every "
        "dimension at its total (plus any filters you fix, such as the "
        "headcount account or a year); if that is empty, it finds which "
        "total hides the data and returns where_with_data — a member for "
        "every dimension that does return data. Pass where_with_data as the "
        "filters of query_cube. When found is false, tell the person no data "
        "exists for that selection instead of guessing more names."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "The TM1 connection."},
            "cube_name": {"type": "string", "description": "The cube to search."},
            "filters": _FILTERS_SCHEMA,
        },
        "required": ["connection_id", "cube_name"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:
        await _require_read(db, user_id, self.required_permission)
        connection, client = await _client_for(
            db, organization_id, kwargs["connection_id"]
        )

        try:
            result = await find_data(
                client,
                connection.id,
                str(kwargs["cube_name"]),
                dict(kwargs.get("filters") or {}),
            )
        except QuerySpecError as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(result, default=str)


class QueryCubeTool(Tool):
    name = "query_cube"
    description = (
        "Run a query built from what you want on the axes, instead of "
        "writing MDX. Every dimension of the cube is placed exactly once: on "
        "an axis, at the member given in filters, or else at its total — so "
        "the query cannot leave a dimension out or name one twice. Returns "
        "the MDX it ran (use that exact string for show_chart or the final "
        "answer) and the first rows. Use find_data first when a query comes "
        "back empty."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "The TM1 connection."},
            "cube_name": {"type": "string", "description": "The cube to read."},
            "columns": {
                **_AXIS_SCHEMA,
                "description": "What runs along the chart (usually time).",
            },
            "rows": {
                "type": "array",
                "items": _AXIS_SCHEMA,
                "maxItems": 2,
                "description": "The breakdown (legend), if any — at most two dimensions.",
            },
            "filters": _FILTERS_SCHEMA,
        },
        "required": ["connection_id", "cube_name", "columns"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:
        await _require_read(db, user_id, self.required_permission)
        connection, client = await _client_for(
            db, organization_id, kwargs["connection_id"]
        )

        try:
            result = await query_cube(
                client,
                connection.id,
                str(kwargs["cube_name"]),
                dict(kwargs["columns"]),
                list(kwargs.get("rows") or []),
                dict(kwargs.get("filters") or {}),
            )
        except QuerySpecError as exc:
            return json.dumps({"error": str(exc)})

        table = result["table"]
        # The MDX first: the stored summary of a tool result is its first
        # 500 characters, and Visualize reads the query back from there.
        return json.dumps(
            {
                "mdx": result["mdx"],
                "cell_count": len(table["rows"]),
                "truncated": table["truncated"],
                "dimensions": table["dimensions"],
                "where": result["where"],
                "rows": table["rows"][:_PREVIEW_ROWS],
                **(
                    {
                        "empty": "No cells. Call find_data with the same filters "
                        "to see where the data is."
                    }
                    if not table["rows"]
                    else {}
                ),
            },
            default=str,
        )
