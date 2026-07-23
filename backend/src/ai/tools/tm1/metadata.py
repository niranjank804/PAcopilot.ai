import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.metadata import dependency_analyzer


class GetCubeDependenciesTool(Tool):

    name = "get_cube_dependencies"
    description = (
        "Get the list of dimensions a TM1 cube uses, from the extracted "
        "metadata graph. Requires metadata extraction to have been run for "
        "the connection first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "cube_name": {
                "type": "string",
                "description": "The name of the cube to look up.",
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

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        cube_name = str(kwargs["cube_name"])

        dimensions = await dependency_analyzer.get_cube_dependencies(
            db, connection_id, organization_id, cube_name
        )

        return json.dumps({"cube": cube_name, "dimensions": dimensions})


class GetDimensionDependentsTool(Tool):

    name = "get_dimension_dependents"
    description = (
        "Get the list of TM1 cubes that use a given dimension, from the "
        "extracted metadata graph — useful for answering 'what breaks if I "
        "change this dimension?'. Requires metadata extraction to have been "
        "run for the connection first."
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

        cubes = await dependency_analyzer.get_dimension_dependents(
            db, connection_id, organization_id, dimension_name
        )

        return json.dumps({"dimension": dimension_name, "cubes": cubes})


class GetObjectRelationshipsTool(Tool):

    name = "get_object_relationships"
    description = (
        "Get every relationship of a TM1 object (cube, dimension, hierarchy, "
        "or process) from the extracted metadata graph, in both directions — "
        "e.g. which processes update a cube, which cubes a rule references. "
        "Requires metadata extraction to have been run for the connection "
        "first."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "object_type": {
                "type": "string",
                "enum": ["cube", "dimension", "hierarchy", "process"],
                "description": "The type of the object to look up.",
            },
            "name": {
                "type": "string",
                "description": (
                    "The name of the object. Hierarchies use the "
                    "'Dimension:Hierarchy' qualified name."
                ),
            },
        },
        "required": ["connection_id", "object_type", "name"],
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
        object_type = str(kwargs["object_type"])
        name = str(kwargs["name"])

        relationships = await dependency_analyzer.get_object_relationships(
            db, connection_id, organization_id, object_type, name
        )

        return json.dumps(relationships)
