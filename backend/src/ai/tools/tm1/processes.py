import difflib
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


class SearchProcessCodeTool(Tool):

    name = "search_process_code"
    description = (
        "Find every TurboIntegrator process whose code contains a given "
        "string, across the whole model. Use this to answer questions like "
        "'which processes write to this cube' or 'where is CellPutN used' "
        "without fetching processes one at a time."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection to query.",
            },
            "search_string": {
                "type": "string",
                "description": (
                    "Text to look for in process code, for example a cube "
                    "name, a function name, or a variable."
                ),
            },
        },
        "required": ["connection_id", "search_string"],
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

        search_string = str(kwargs["search_string"]).strip()
        if not search_string:
            return json.dumps({"error": "search_string must not be empty."})

        matches = await tm1_integration_service.search_process_code(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            search_string,
        )

        return json.dumps(
            {
                "search_string": search_string,
                "match_count": len(matches),
                "processes": matches,
            }
        )


class DiffProcessTool(Tool):

    name = "diff_process"
    description = (
        "Compare a process on the server against text you supply, section by "
        "section, and return a unified diff. Use this to check whether a "
        "local copy matches what is deployed, or what changed between two "
        "versions of a process."
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
                "description": "The process on the server.",
            },
            "prolog": {"type": "string", "description": "Expected Prolog code."},
            "metadata": {"type": "string", "description": "Expected Metadata code."},
            "data": {"type": "string", "description": "Expected Data code."},
            "epilog": {"type": "string", "description": "Expected Epilog code."},
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

        process_name = str(kwargs["process_name"])

        process = await tm1_integration_service.get_process(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            process_name,
        )

        server_sections = {
            "prolog": process.prolog,
            "metadata": process.metadata,
            "data": process.data,
            "epilog": process.epilog,
        }

        diffs = {}
        compared = []

        for section, server_code in server_sections.items():
            if section not in kwargs or kwargs[section] is None:
                continue  # only compare what the caller supplied

            compared.append(section)
            expected = str(kwargs[section])

            lines = list(
                difflib.unified_diff(
                    (server_code or "").splitlines(),
                    expected.splitlines(),
                    fromfile=f"server:{section}",
                    tofile=f"supplied:{section}",
                    lineterm="",
                )
            )
            if lines:
                diffs[section] = "\n".join(lines[:400])

        if not compared:
            return json.dumps(
                {
                    "error": "Supply at least one of prolog, metadata, data "
                    "or epilog to compare against."
                }
            )

        return json.dumps(
            {
                "process": process_name,
                "sections_compared": compared,
                "identical": not diffs,
                "sections_differing": list(diffs),
                "diffs": diffs,
            }
        )
