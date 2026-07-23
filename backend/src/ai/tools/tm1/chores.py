import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service


class ListChoresTool(Tool):

    name = "list_chores"
    description = "List the names of all scheduled chores in a TM1 model."
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

        chores = await tm1_integration_service.list_chores(
            db, connection_id, organization_id
        )

        return json.dumps({"chores": chores})


class GetChoreTool(Tool):

    name = "get_chore"
    description = (
        "Get details about a TM1 chore, including whether it's active and "
        "which TurboIntegrator processes it runs."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "chore_name": {
                "type": "string",
                "description": "The name of the chore to look up.",
            },
        },
        "required": ["connection_id", "chore_name"],
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
        chore_name = str(kwargs["chore_name"])

        chore = await tm1_integration_service.get_chore(
            db, connection_id, organization_id, chore_name
        )

        return json.dumps(
            {
                "name": chore.name,
                "active": chore.active,
                "process_names": chore.process_names,
            }
        )
