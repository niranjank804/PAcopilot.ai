"""Model structure tools: views, subsets, attributes, hierarchies, state.

`get_element_context` is the one worth noticing. It answers "tell me about
this element" - parents, what sits under it, which attributes exist - in a
single call. A retrieval surface makes the model ask for each of those
separately and stitch them together, which costs four round trips and
usually ends with the model forgetting to ask for one of them.
"""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service
from src.tm1.services import cell_service, structure_service
from src.tm1.services.structure_service import MAX_ITEMS, cap

CONNECTION_ID_SCHEMA = {
    "type": "string",
    "description": "The ID of the TM1 connection to query.",
}


class _StructureTool(Tool):

    required_permission = "tm1.read"

    async def _authorize(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )


class ListCubeViewsTool(_StructureTool):

    name = "list_cube_views"
    description = (
        "List the public and private view names defined on a cube. Use this "
        "to find an existing view before writing an MDX query, or to check "
        "what a process's datasource view is called."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {"type": "string", "description": "The cube."},
        },
        "required": ["connection_id", "cube_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        views = await tm1_integration_service.list_views(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            str(kwargs["cube_name"]),
        )
        public, public_cut = cap(views["public"])
        private, private_cut = cap(views["private"])

        return json.dumps(
            {
                "cube": kwargs["cube_name"],
                "public_views": public,
                "private_views": private,
                "truncated": public_cut or private_cut,
            }
        )


class ListDimensionSubsetsTool(_StructureTool):

    name = "list_dimension_subsets"
    description = (
        "List the public subsets defined on a dimension hierarchy. Use this "
        "to find an existing element selection instead of rebuilding one."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "dimension_name": {"type": "string", "description": "The dimension."},
            "hierarchy_name": {
                "type": "string",
                "description": "Hierarchy name. Defaults to the dimension name.",
            },
        },
        "required": ["connection_id", "dimension_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        dimension = str(kwargs["dimension_name"])
        hierarchy = str(kwargs.get("hierarchy_name") or dimension)

        subsets = await tm1_integration_service.list_subsets(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            dimension,
            hierarchy,
        )
        items, truncated = cap(subsets)

        return json.dumps(
            {
                "dimension": dimension,
                "hierarchy": hierarchy,
                "count": len(subsets),
                "subsets": items,
                "truncated": truncated,
            }
        )


class GetDimensionAttributesTool(_StructureTool):

    name = "get_dimension_attributes"
    description = (
        "List the attributes defined on a dimension hierarchy, with their "
        "types, and the hierarchies the dimension has along with each "
        "default member. Use this before writing code that reads ATTRS or "
        "ATTRN, so the attribute name is real."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "dimension_name": {"type": "string", "description": "The dimension."},
            "hierarchy_name": {
                "type": "string",
                "description": "Hierarchy name. Defaults to the dimension name.",
            },
        },
        "required": ["connection_id", "dimension_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        dimension = str(kwargs["dimension_name"])
        hierarchy = str(kwargs.get("hierarchy_name") or dimension)

        connection, client = await tm1_integration_service.connect(
            db, connection_id, organization_id
        )

        attributes, hierarchies, default_member = await asyncio.gather(
            structure_service.get_attribute_definitions(
                client, connection.id, dimension, hierarchy
            ),
            structure_service.list_hierarchies(client, connection.id, dimension),
            structure_service.get_default_member(
                client, connection.id, dimension, hierarchy
            ),
        )

        return json.dumps(
            {
                "dimension": dimension,
                "hierarchy": hierarchy,
                "attributes": attributes,
                "hierarchies": hierarchies,
                "default_member": default_member,
            }
        )


class GetElementContextTool(_StructureTool):

    name = "get_element_context"
    description = (
        "Everything about one element in a single call: its parents, the "
        "leaf elements beneath it if it is a consolidation, and its "
        "attribute values (read from the dimension's attribute control "
        "cube). Use this when a number looks wrong at a consolidation and "
        "you need to know what rolls into it, or to read an alias."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "dimension_name": {"type": "string", "description": "The dimension."},
            "element_name": {"type": "string", "description": "The element."},
            "hierarchy_name": {
                "type": "string",
                "description": "Hierarchy name. Defaults to the dimension name.",
            },
        },
        "required": ["connection_id", "dimension_name", "element_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        dimension = str(kwargs["dimension_name"])
        element = str(kwargs["element_name"])
        hierarchy = str(kwargs.get("hierarchy_name") or dimension)

        async def safe(coro, fallback):
            # An element with no children is an ordinary answer, not an
            # error; TM1 raises for a leaf, so absorb it here.
            try:
                return await coro
            except Exception:  # noqa: BLE001
                return fallback

        connection, client = await tm1_integration_service.connect(
            db, connection_id, organization_id
        )

        parents, leaves, attributes = await asyncio.gather(
            safe(
                structure_service.get_parents(
                    client, connection.id, dimension, hierarchy, element
                ),
                [],
            ),
            safe(
                structure_service.get_leaves_under(
                    client, connection.id, dimension, hierarchy, element
                ),
                [],
            ),
            safe(
                structure_service.get_attribute_definitions(
                    client, connection.id, dimension, hierarchy
                ),
                [],
            ),
        )

        # Values live in the attribute control cube and are only meaningful
        # on the dimension's own hierarchy. A failure here (no attribute
        # cube, an alternate hierarchy) leaves the values out and says so.
        attribute_values: dict | None = None
        attribute_note = None

        if attributes and hierarchy == dimension:
            try:
                attribute_values = await cell_service.read_attribute_values(
                    client,
                    connection.id,
                    dimension,
                    element,
                    [a["name"] for a in attributes][:MAX_ITEMS],
                )
            except Exception as exc:  # noqa: BLE001
                attribute_note = (
                    "Attribute values could not be read "
                    f"({type(exc).__name__}); definitions are listed."
                )
        elif attributes:
            attribute_note = (
                "Attribute values are read on the dimension's own hierarchy "
                "only; definitions are listed."
            )

        capped_leaves, truncated = cap(leaves)

        return json.dumps(
            {
                "dimension": dimension,
                "hierarchy": hierarchy,
                "element": element,
                "parents": parents,
                "is_consolidation": bool(leaves),
                "leaf_count": len(leaves),
                "leaves": capped_leaves,
                "leaves_truncated": truncated,
                "attributes": [a["name"] for a in attributes],
                "attribute_values": attribute_values,
                "attribute_note": attribute_note,
                "note": (
                    f"Only the first {MAX_ITEMS} leaves are listed."
                    if truncated
                    else None
                ),
            }
        )


class GetServerStateTool(_StructureTool):

    name = "get_server_state"
    description = (
        "Report the TM1 server's version, how many sessions are open, and "
        "which threads are currently running with what they are doing. Use "
        "this when the server is slow or a process appears to hang."
    )
    input_schema = {
        "type": "object",
        "properties": {"connection_id": CONNECTION_ID_SCHEMA},
        "required": ["connection_id"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        state = await tm1_integration_service.get_server_state(
            db, uuid.UUID(str(kwargs["connection_id"])), organization_id
        )
        return json.dumps(state, default=str)


class GetViewTool(_StructureTool):

    name = "get_view"
    description = (
        "Show what a cube view selects, as MDX: the view's own MDX for an "
        "MDX view, or TM1py's rendering of the rows, columns and titles for "
        "a native view. Use this to explain a process's datasource view or "
        "to reuse a view's selection in a query."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube_name": {"type": "string", "description": "The cube."},
            "view_name": {"type": "string", "description": "The view."},
            "private": {
                "type": "boolean",
                "description": "Read a private view of the connection's user. Default false.",
            },
        },
        "required": ["connection_id", "cube_name", "view_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        view = await tm1_integration_service.run(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            structure_service.get_view,
            str(kwargs["cube_name"]),
            str(kwargs["view_name"]),
            bool(kwargs.get("private")),
        )

        return json.dumps(view)


class GetSubsetTool(_StructureTool):

    name = "get_subset"
    description = (
        "Show a subset's definition: the MDX expression of a dynamic subset, "
        f"or the elements of a static one (first {MAX_ITEMS}). Use this to "
        "see exactly which elements a process or view works on."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "dimension_name": {"type": "string", "description": "The dimension."},
            "subset_name": {"type": "string", "description": "The subset."},
            "hierarchy_name": {
                "type": "string",
                "description": "Hierarchy name. Defaults to the dimension name.",
            },
            "private": {
                "type": "boolean",
                "description": "Read a private subset of the connection's user. Default false.",
            },
        },
        "required": ["connection_id", "dimension_name", "subset_name"],
    }

    async def execute(
        self, db: AsyncSession, *, organization_id, user_id, **kwargs
    ) -> str:
        await self._authorize(db, user_id)

        dimension = str(kwargs["dimension_name"])

        subset = await tm1_integration_service.run(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            structure_service.get_subset,
            dimension,
            str(kwargs.get("hierarchy_name") or dimension),
            str(kwargs["subset_name"]),
            bool(kwargs.get("private")),
        )

        return json.dumps(subset)
