import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service


class ExecuteMDXTool(Tool):

    name = "execute_mdx"
    description = (
        "Execute a read-only MDX query against a TM1 cube and return cell "
        "values as a flat map of element-path to value. Always confirm real "
        "cube, dimension, and element names with other tools first — never "
        "guess member names, they rarely match natural-language phrasing "
        "exactly. Results are capped at 500 cells; narrow the query (e.g. "
        "add a WHERE clause) if you need a smaller slice."
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
                "description": "The MDX query to execute.",
            },
        },
        "required": ["connection_id", "mdx"],
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
        mdx = str(kwargs["mdx"])

        result = await tm1_integration_service.execute_mdx(
            db, connection_id, organization_id, mdx
        )

        return json.dumps({"cells": result.cells, "cell_count": len(result.cells)})
