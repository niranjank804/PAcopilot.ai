"""Incident mode, for the agents: "production allocation is wrong".

The same investigation as the Team page's Report incident, read-only and
not saved: the environment, the affected cube and who writes it, recent
changes and runs, model differences, rules and alerts, ranked into
suspects with a suggested mitigation each. The agent explains them; any
mitigation is a change a person approves.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException, ValidationException
from src.repositories.auth_repository import auth_repository
from src.services.incident_service import DEFAULT_WINDOW_HOURS, incident_service
from src.tm1.service import tm1_integration_service


class InvestigateIncidentTool(Tool):

    name = "investigate_incident"
    description = (
        "Investigate a problem on a TM1 server — numbers that look wrong in "
        "a cube, or a process that failed. Gathers, for the time window: the "
        "environment, the processes that write the cube and the cubes its "
        "rules read, PA-Copilot changes applied or failed there, process runs "
        "and failures, model differences, rule findings and open alerts; and "
        "ranks suspects with a suggested mitigation each (roll back a change, "
        "diagnose and re-run a process, review). Reads only. Use it first "
        "when the user reports an incident, then explain the top suspects and "
        "the evidence; never present a mitigation as done."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "The TM1 connection."},
            "cube_name": {"type": "string", "description": "The cube whose numbers look wrong."},
            "process_name": {"type": "string", "description": "Or: the process that failed."},
            "window_hours": {"type": "integer", "description": "How far back to look (default 48)."},
        },
        "required": ["connection_id"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(f"Missing permission: {self.required_permission}")
        cube = (kwargs.get("cube_name") or "").strip() or None
        process = (kwargs.get("process_name") or "").strip() or None
        if not (cube or process):
            raise ValidationException("Name the cube that looks wrong, or the process that failed.")
        connection = await tm1_integration_service.get_connection(
            db, uuid.UUID(str(kwargs["connection_id"])), organization_id, user_id=user_id
        )
        findings = await incident_service.gather(
            db, connection, cube=cube, process=process,
            window_hours=kwargs.get("window_hours") or DEFAULT_WINDOW_HOURS,
        )
        return json.dumps(findings, default=str)
