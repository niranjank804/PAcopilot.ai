import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException, ValidationException
from src.repositories.auth_repository import auth_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.deployment.change_service import change_service
from src.tm1.service import tm1_integration_service
from src.tm1.services import process_service

_HUMAN_REVIEW_NOTE = (
    "This is a DRAFT only — it has NOT been applied to the TM1 server. "
    "A human administrator with deploy rights must review and execute it "
    "in the console."
)


async def _create_draft(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    connection_id: str,
    change_type: str,
    target_name: str,
    new_content: dict,
) -> str:
    change = await change_service.create_change(
        db,
        connection_id=uuid.UUID(str(connection_id)),
        organization_id=organization_id,
        created_by=user_id,
        change_type=change_type,
        target_name=target_name,
        new_content=new_content,
    )

    return json.dumps(
        {
            "draft_change_id": str(change.id),
            "status": change.status,
            "validation_errors": change.validation_errors or [],
            "impact": change.impact or [],
            "note": _HUMAN_REVIEW_NOTE,
        }
    )


class ProposeRuleUpdateTool(Tool):

    name = "propose_rule_update"
    description = (
        "Propose an update to a cube's rules as a DRAFT change for human "
        "review. The draft includes impact analysis from the metadata "
        "graph. You cannot execute changes — a human administrator "
        "deploys drafts."
    )
    required_permission = "tm1.write"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection.",
            },
            "cube_name": {
                "type": "string",
                "description": "The cube whose rules to update.",
            },
            "rules": {
                "type": "string",
                "description": "The complete proposed rule text.",
            },
        },
        "required": ["connection_id", "cube_name", "rules"],
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
                "You do not have permission to draft TM1 changes."
            )

        return await _create_draft(
            db,
            organization_id=organization_id,
            user_id=user_id,
            connection_id=kwargs["connection_id"],
            change_type="update_rules",
            target_name=str(kwargs["cube_name"]),
            new_content={"rules": str(kwargs["rules"])},
        )


class ProposeProcessUpdateTool(Tool):

    name = "propose_process_update"
    description = (
        "Propose creating or updating a TurboIntegrator process as a DRAFT "
        "change for human review. The draft is compile-validated against "
        "the server without being saved. You cannot execute changes — a "
        "human administrator deploys drafts."
    )
    required_permission = "tm1.write"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection.",
            },
            "process_name": {
                "type": "string",
                "description": "The process to create or update.",
            },
            "create_new": {
                "type": "boolean",
                "description": (
                    "true to create a new process, false to update an "
                    "existing one."
                ),
            },
            "prolog": {"type": "string", "description": "Prolog code."},
            "metadata": {"type": "string", "description": "Metadata code."},
            "data": {"type": "string", "description": "Data code."},
            "epilog": {"type": "string", "description": "Epilog code."},
            "datasource_type": {
                "type": "string",
                "enum": ["None", "ASCII"],
                "description": (
                    "Datasource. Use 'None' for a self-contained process. "
                    "Use 'ASCII' for a delimited-file loader — required for "
                    "source column variables (v1, v2, ...) to compile."
                ),
            },
            "datasource_name": {
                "type": "string",
                "description": (
                    "For ASCII: the data file path on the TM1 server "
                    "(the administrator can confirm or change it at deploy)."
                ),
            },
            "ascii_delimiter": {
                "type": "string",
                "description": "For ASCII: the column delimiter. Default ','.",
            },
            "ascii_header_records": {
                "type": "integer",
                "description": "For ASCII: header rows to skip. Default 0.",
            },
            "variables": {
                "type": "array",
                "description": (
                    "Datasource source columns, in order. Declare these so "
                    "references like v1, v2 compile against an ASCII/view "
                    "datasource."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": ["String", "Numeric"]},
                    },
                    "required": ["name", "type"],
                },
            },
            "parameters": {
                "type": "array",
                "description": (
                    "Process parameters (e.g. pSourceFile). Declare these so "
                    "the process compiles when the code references them."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": ["String", "Numeric"]},
                        "value": {
                            "type": "string",
                            "description": "Default value (numbers as text).",
                        },
                        "prompt": {"type": "string"},
                    },
                    "required": ["name", "type"],
                },
            },
        },
        "required": ["connection_id", "process_name", "create_new"],
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
                "You do not have permission to draft TM1 changes."
            )

        new_content: dict = {
            key: str(kwargs[key])
            for key in ("prolog", "metadata", "data", "epilog")
            if key in kwargs
        }

        # Datasource / variable / parameter definitions travel as-is (lists
        # and scalars); _build_process applies them to the TM1py Process so
        # source columns and parameters resolve at compile time.
        for key in (
            "datasource_type",
            "datasource_name",
            "ascii_delimiter",
            "ascii_header_records",
            "variables",
            "parameters",
        ):
            if kwargs.get(key) is not None:
                new_content[key] = kwargs[key]

        return await _create_draft(
            db,
            organization_id=organization_id,
            user_id=user_id,
            connection_id=kwargs["connection_id"],
            change_type=(
                "create_process" if kwargs["create_new"] else "update_process"
            ),
            target_name=str(kwargs["process_name"]),
            new_content=new_content,
        )


def copy_content(source_name: str, body: dict) -> dict:
    """Draft content for an exact copy of a process body.

    `source_body` is what gets built and deployed. The code tabs, datasource
    type, variables and parameters are repeated in the ordinary draft format
    so the review screen shows the code and static analysis can check it —
    without them every source variable would read as undefined.
    """

    datasource = body.get("DataSource") or {}

    return {
        "copy_of": source_name,
        "prolog": body.get("PrologProcedure") or "",
        "metadata": body.get("MetadataProcedure") or "",
        "data": body.get("DataProcedure") or "",
        "epilog": body.get("EpilogProcedure") or "",
        "datasource_type": datasource.get("Type") or "None",
        "variables": [
            {"name": variable["Name"], "type": variable.get("Type") or "String"}
            for variable in body.get("Variables") or []
        ],
        "parameters": [
            {
                "name": parameter["Name"],
                "type": parameter.get("Type") or "String",
                "value": (
                    "" if parameter.get("Value") is None else str(parameter["Value"])
                ),
                "prompt": parameter.get("Prompt") or "",
            }
            for parameter in body.get("Parameters") or []
        ],
        "source_body": body,
    }


class ProposeProcessCopyTool(Tool):

    name = "propose_process_copy"
    description = (
        "Propose an exact copy of an existing TurboIntegrator process under a "
        "new name, as a DRAFT change for human review. The copy is taken "
        "from the server, not retyped, so code, datasource, variables and "
        "parameters match the original. Use this whenever the user asks to "
        "copy, clone or duplicate a process; to change the copy afterwards, "
        "use propose_process_update on the new name. You cannot execute "
        "changes — a human administrator deploys drafts."
    )
    required_permission = "tm1.write"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {
                "type": "string",
                "description": "The ID of the TM1 connection.",
            },
            "source_process": {
                "type": "string",
                "description": "The existing process to copy.",
            },
            "new_process_name": {
                "type": "string",
                "description": (
                    "Name for the copy. Must not already exist. If the user "
                    "gave none, use the original name followed by ' - Copy'."
                ),
            },
        },
        "required": ["connection_id", "source_process", "new_process_name"],
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
                "You do not have permission to draft TM1 changes."
            )

        source = str(kwargs["source_process"]).strip()
        new_name = str(kwargs["new_process_name"]).strip()

        # TM1 object names are case-insensitive, so 'it_load data' is the
        # original, not a copy of it.
        if not new_name or new_name.lower() == source.lower():
            raise ValidationException(
                "The copy needs a name different from the original process."
            )

        connection = await tm1_integration_service.get_connection(
            db, uuid.UUID(str(kwargs["connection_id"])), organization_id
        )
        client = await tm1_connection_manager.get_client(connection)
        body = await process_service.get_process_body(client, connection.id, source)

        content = copy_content(source, body)

        draft = json.loads(
            await _create_draft(
                db,
                organization_id=organization_id,
                user_id=user_id,
                connection_id=str(connection.id),
                change_type="create_process",
                target_name=new_name,
                new_content=content,
            )
        )

        datasource = body.get("DataSource") or {}
        draft["copied_from"] = source
        draft["new_process_name"] = new_name
        draft["copy_summary"] = {
            "datasource_type": content["datasource_type"],
            "datasource_name": datasource.get("dataSourceNameForServer"),
            "parameters": [parameter["name"] for parameter in content["parameters"]],
            "variables": [variable["name"] for variable in content["variables"]],
            "code_lines": {
                tab: len((content[tab] or "").splitlines())
                for tab in ("prolog", "metadata", "data", "epilog")
            },
        }

        return json.dumps(draft)
