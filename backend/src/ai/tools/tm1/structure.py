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

        attributes, hierarchies = await asyncio.gather(
            tm1_integration_service.get_attribute_definitions(
                db, connection_id, organization_id, dimension, hierarchy
            ),
            tm1_integration_service.list_hierarchies(
                db, connection_id, organization_id, dimension
            ),
        )

        default_member = await tm1_integration_service.get_default_member(
            db, connection_id, organization_id, dimension, hierarchy
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
        "leaf elements beneath it if it is a consolidation, and the "
        "attributes defined on its dimension. Use this when a number looks "
        "wrong at a consolidation and you need to know what rolls into it."
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

        parents, leaves, attributes = await asyncio.gather(
            safe(
                tm1_integration_service.get_element_parents(
                    db, connection_id, organization_id, dimension, hierarchy, element
                ),
                [],
            ),
            safe(
                tm1_integration_service.get_leaves_under(
                    db, connection_id, organization_id, dimension, hierarchy, element
                ),
                [],
            ),
            safe(
                tm1_integration_service.get_attribute_definitions(
                    db, connection_id, organization_id, dimension, hierarchy
                ),
                [],
            ),
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
