"""Tools that read TM1 server and process logs.

These close the loop the product was missing: before this, the agent could
draft a change but had no way to see what happened when a human ran it. The
developer had to leave, run it in PAW, read the log by eye, and paste the
error back into chat.

All read-only. Nothing here executes anything.
"""

import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.service import tm1_integration_service
from src.tm1.services.log_service import (
    MAX_ROWS,
    parse_error_locations,
    truncate_log,
)

CONNECTION_ID_SCHEMA = {
    "type": "string",
    "description": "The ID of the TM1 connection to query.",
}

# How many lines of process code to show around a reported error line.
CONTEXT_LINES = 4


def parse_timestamp(value) -> datetime | None:
    """Accept an ISO 8601 string from the model, or nothing.

    A malformed timestamp is treated as absent rather than raising: the model
    guessing a date format badly should narrow the search, not fail the call.
    """

    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class _ReadLogTool(Tool):
    """Shared permission check for every log read."""

    required_permission = "tm1.read"

    async def _authorize(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read TM1 data."
            )


class GetMessageLogTool(_ReadLogTool):

    name = "get_message_log"
    description = (
        "Read recent entries from the TM1 server message log, newest first. "
        "Use this to find out what the server was doing when something failed "
        f"- for example why a process aborted. Returns at most {MAX_ROWS} rows."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "top": {
                "type": "integer",
                "description": f"Maximum entries to return (capped at {MAX_ROWS}).",
            },
            "since": {
                "type": "string",
                "description": "Only entries at or after this ISO 8601 timestamp.",
            },
            "until": {
                "type": "string",
                "description": "Only entries at or before this ISO 8601 timestamp.",
            },
            "level": {
                "type": "string",
                "description": "Filter by level, for example ERROR, WARNING or INFO.",
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

        await self._authorize(db, user_id)

        entries = await tm1_integration_service.get_message_log(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            top=kwargs.get("top"),
            since=parse_timestamp(kwargs.get("since")),
            until=parse_timestamp(kwargs.get("until")),
            level=kwargs.get("level"),
        )

        return json.dumps({"count": len(entries), "entries": entries}, default=str)


class GetTransactionLogTool(_ReadLogTool):

    name = "get_transaction_log"
    description = (
        "Read recent cell changes from the TM1 transaction log, newest first. "
        "Use this to answer who or what changed a value, and when. Can be "
        f"filtered by cube and by user. Returns at most {MAX_ROWS} rows."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "cube": {
                "type": "string",
                "description": "Only changes to this cube.",
            },
            "user": {
                "type": "string",
                "description": "Only changes made by this TM1 user.",
            },
            "since": {
                "type": "string",
                "description": "Only entries at or after this ISO 8601 timestamp.",
            },
            "until": {
                "type": "string",
                "description": "Only entries at or before this ISO 8601 timestamp.",
            },
            "top": {
                "type": "integer",
                "description": f"Maximum entries to return (capped at {MAX_ROWS}).",
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

        await self._authorize(db, user_id)

        entries = await tm1_integration_service.get_transaction_log(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            cube=kwargs.get("cube"),
            user=kwargs.get("user"),
            since=parse_timestamp(kwargs.get("since")),
            until=parse_timestamp(kwargs.get("until")),
            top=kwargs.get("top"),
        )

        return json.dumps({"count": len(entries), "entries": entries}, default=str)


class GetProcessErrorLogTool(_ReadLogTool):

    name = "get_process_error_log"
    description = (
        "Read the error log a TurboIntegrator process wrote when it failed. "
        "Give a process name to read its most recent log, or a specific log "
        "file name. Call list_process_error_logs first if you need to choose."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {
                "type": "string",
                "description": "Read the most recent error log for this process.",
            },
            "file_name": {
                "type": "string",
                "description": "Read this exact error log file instead.",
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

        await self._authorize(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        file_name = kwargs.get("file_name")
        process_name = kwargs.get("process_name")

        if not file_name:
            if not process_name:
                return json.dumps(
                    {"error": "Provide either process_name or file_name."}
                )

            names = await tm1_integration_service.list_process_error_logs(
                db, connection_id, organization_id, process_name=process_name, top=1
            )
            if not names:
                return json.dumps(
                    {
                        "process_name": process_name,
                        "found": False,
                        "message": "No error log exists for this process. It has "
                        "not failed, or the logs have been cleared.",
                    }
                )
            file_name = names[0]

        content = await tm1_integration_service.get_process_error_log(
            db, connection_id, organization_id, str(file_name)
        )

        return json.dumps(
            {
                "file_name": file_name,
                "found": bool(content),
                "content": truncate_log(content),
                "error_locations": parse_error_locations(content),
            }
        )


class ListProcessErrorLogsTool(_ReadLogTool):

    name = "list_process_error_logs"
    description = (
        "List the error log files on the server, newest first. Optionally "
        "restrict to one process. Use this to see whether a process has "
        "failed recently and how often."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {
                "type": "string",
                "description": "Only logs written by this process.",
            },
            "top": {
                "type": "integer",
                "description": f"Maximum files to return (capped at {MAX_ROWS}).",
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

        await self._authorize(db, user_id)

        names = await tm1_integration_service.list_process_error_logs(
            db,
            uuid.UUID(str(kwargs["connection_id"])),
            organization_id,
            process_name=kwargs.get("process_name"),
            top=kwargs.get("top"),
        )

        return json.dumps({"count": len(names), "log_files": names})


class MapLogErrorToCodeTool(_ReadLogTool):

    name = "map_log_error_to_code"
    description = (
        "Resolve the errors in a failed TurboIntegrator process's log back to "
        "the exact lines of its code, with surrounding context. Use this as "
        "the first step when a process has aborted - it answers 'what broke "
        "and where' in one call instead of reading the log and the code "
        "separately."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "process_name": {
                "type": "string",
                "description": "The process that failed.",
            },
            "file_name": {
                "type": "string",
                "description": (
                    "A specific error log file. Defaults to the most recent "
                    "log for this process."
                ),
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

        await self._authorize(db, user_id)

        connection_id = uuid.UUID(str(kwargs["connection_id"]))
        process_name = str(kwargs["process_name"])
        file_name = kwargs.get("file_name")

        if not file_name:
            names = await tm1_integration_service.list_process_error_logs(
                db, connection_id, organization_id, process_name=process_name, top=1
            )
            if not names:
                return json.dumps(
                    {
                        "process_name": process_name,
                        "found": False,
                        "message": "No error log exists for this process.",
                    }
                )
            file_name = names[0]

        content = await tm1_integration_service.get_process_error_log(
            db, connection_id, organization_id, str(file_name)
        )
        locations = parse_error_locations(content)

        if not locations:
            # Common and not a bug: an aborted process often logs a ProcessQuit
            # with no line reference at all. Say so rather than returning
            # nothing and letting the model invent a cause.
            return json.dumps(
                {
                    "process_name": process_name,
                    "file_name": file_name,
                    "resolved": False,
                    "message": "The log reports no line number, so it cannot be "
                    "mapped to code. The raw log is included.",
                    "log": truncate_log(content),
                }
            )

        process = await tm1_integration_service.get_process(
            db, connection_id, organization_id, process_name
        )
        sections = {
            "prolog": process.prolog,
            "metadata": process.metadata,
            "data": process.data,
            "epilog": process.epilog,
        }

        resolved = []
        for location in locations:
            code = sections.get(location["section"]) or ""
            lines = code.splitlines()
            index = location["line_number"] - 1  # TM1 reports 1-based

            if not 0 <= index < len(lines):
                resolved.append(
                    {
                        **location,
                        "code_line": None,
                        "note": "Line number is outside the current code. The "
                        "process has probably been edited since it failed.",
                    }
                )
                continue

            start = max(0, index - CONTEXT_LINES)
            end = min(len(lines), index + CONTEXT_LINES + 1)

            resolved.append(
                {
                    **location,
                    "code_line": lines[index].strip(),
                    "context": [
                        {
                            "line_number": n + 1,
                            "text": lines[n],
                            "is_error_line": n == index,
                        }
                        for n in range(start, end)
                    ],
                }
            )

        return json.dumps(
            {
                "process_name": process_name,
                "file_name": file_name,
                "resolved": True,
                "error_count": len(resolved),
                "errors": resolved,
            }
        )
