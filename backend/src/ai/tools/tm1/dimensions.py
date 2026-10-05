import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service


class ListDimensionsTool(Tool):

    name = "list_dimensions"
    description = (
        "List the names of all dimensions in a TM1 model. Control "
        "dimensions are hidden unless include_control is true."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "include_control": {
                "type": "boolean",
                "description": (
                    "Also list control objects (names starting with '}'), "
                    "e.g. }ClientGroups or }ElementAttributes_… . Default false."
                ),
            },
        },
        "required": ["connection_id"],
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

        connection_id = uuid.UUID(str(kwargs["connection_id"]))

        dimensions = await tm1_integration_service.list_dimensions(
            db,
            connection_id,
            organization_id,
            include_control=bool(kwargs.get("include_control")),
        )

        return json.dumps({"dimensions": dimensions})


class GetDimensionTool(Tool):

    name = "get_dimension"
    description = (
        "Get a TM1 dimension's hierarchies and how many elements each has "
        "(total, leaf, consolidated, string), counted by the server. Use it "
        "to answer how many elements a dimension has — do not list elements "
        "to count them."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "dimension_name": {
                "type": "string",
                "description": "The name of the dimension to look up.",
            },
        },
        "required": ["connection_id", "dimension_name"],
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

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        dimension_name = str(kwargs["dimension_name"])

        dimension = await tm1_integration_service.get_dimension(
            db, connection_id, organization_id, dimension_name, with_counts=True
        )

        return json.dumps(
            {
                "name": dimension.name,
                "hierarchy_names": dimension.hierarchy_names,
                "element_counts": dimension.element_counts,
            }
        )


class ListDimensionElementsTool(Tool):

    name = "list_dimension_elements"
    description = (
        "List the real element (member) names in a TM1 dimension — use this "
        "to confirm actual names (e.g. how a month or account is really "
        "spelled) before writing MDX. Capped at 200 elements."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "dimension_name": {
                "type": "string",
                "description": "The name of the dimension to look up.",
            },
            "hierarchy_name": {
                "type": "string",
                "description": (
                    "The hierarchy to read elements from. Defaults to the "
                    "dimension's default hierarchy (same name as the "
                    "dimension) if omitted."
                ),
            },
        },
        "required": ["connection_id", "dimension_name"],
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

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        dimension_name = str(kwargs["dimension_name"])
        hierarchy_name = kwargs.get("hierarchy_name")

        elements = await tm1_integration_service.list_dimension_elements(
            db,
            connection_id,
            organization_id,
            dimension_name,
            str(hierarchy_name) if hierarchy_name else None,
        )

        return json.dumps({"dimension_name": dimension_name, "elements": elements})
