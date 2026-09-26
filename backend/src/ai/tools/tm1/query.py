import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
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
