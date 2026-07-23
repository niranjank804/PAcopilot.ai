import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool, truncate_code
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service


class ListCubesTool(Tool):

    name = "list_cubes"
    description = "List the names of all cubes in a TM1 model."
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
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

        cubes = await tm1_integration_service.list_cubes(
            db, connection_id, organization_id
        )

        return json.dumps({"cubes": cubes})


class GetCubeTool(Tool):

    name = "get_cube"
    description = "Get details about a specific TM1 cube, including its dimensions and whether it has rules."
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

        cube = await tm1_integration_service.get_cube(
            db, connection_id, organization_id, cube_name
        )

        return json.dumps(
            {
                "name": cube.name,
                "dimensions": cube.dimensions,
                "has_rules": cube.has_rules,
            }
        )


class GetCubeRulesTool(Tool):

    name = "get_cube_rules"
    description = (
        "Get the rule text of a TM1 cube, or null if the cube has no rules "
        "(long rule text is truncated)."
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
                "description": "The name of the cube whose rules to fetch.",
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

        rules = await tm1_integration_service.get_cube_rules(
            db, connection_id, organization_id, cube_name
        )

        return json.dumps(
            {
                "name": cube_name,
                "rules": truncate_code(rules) if rules is not None else None,
            }
        )
