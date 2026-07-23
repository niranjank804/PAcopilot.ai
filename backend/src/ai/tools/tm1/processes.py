import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool, truncate_code
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service


class ListProcessesTool(Tool):

    name = "list_processes"
    description = "List the names of all TurboIntegrator (TI) processes in a TM1 model."
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

        processes = await tm1_integration_service.list_processes(
            db, connection_id, organization_id
        )

        return json.dumps({"processes": processes})


class GetProcessTool(Tool):

    name = "get_process"
    description = (
        "Get details about a TurboIntegrator (TI) process, including its "
        "datasource and the Prolog/Metadata/Data/Epilog code sections "
        "(long sections are truncated)."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "process_name": {
                "type": "string",
                "description": "The name of the TI process to look up.",
            },
        },
        "required": ["connection_id", "process_name"],
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
        process_name = str(kwargs["process_name"])

        process = await tm1_integration_service.get_process(
            db, connection_id, organization_id, process_name
        )

        return json.dumps(
            {
                "name": process.name,
                "datasource_type": process.datasource_type,
                "datasource_name": process.datasource_name,
                "datasource_view": process.datasource_view,
                "has_security_access": process.has_security_access,
                "parameter_names": process.parameter_names,
                "prolog": truncate_code(process.prolog),
                "metadata": truncate_code(process.metadata),
                "data": truncate_code(process.data),
                "epilog": truncate_code(process.epilog),
            }
        )
