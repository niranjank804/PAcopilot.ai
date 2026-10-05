"""Monitoring, for the agents: suggest a rule, read the alerts.

"Alert me if Workforce Planning takes more than twice its 30-day average"
becomes a proposed rule. It is not checked until the user turns it on on
the Alerts page — the assistant never starts watching anything by itself,
and a rule only ever reads TM1.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.services.monitoring_rules_service import KINDS, describe, monitoring_rules_service


async def _authorize(db: AsyncSession, user_id: uuid.UUID, permission: str) -> None:
    if not await auth_repository.user_has_permission(db, user_id, permission):
        raise PermissionDeniedException(f"Missing permission: {permission}")


class ProposeMonitorTool(Tool):

    name = "propose_monitor"
    description = (
        "Suggest a monitoring rule on a TM1 server when the user asks to be "
        "alerted about something. Kinds: process_failure (params: optional "
        "process_name), performance_regression (params: process_name, factor "
        "e.g. 2 for twice the average, window_days e.g. 30), dimension_growth "
        "(params: dimension_name, max_growth_percent), security_change, "
        "model_change, deployment. It is saved as a PROPOSAL: nothing is "
        "checked until the user turns it on on the Alerts page. Rules only "
        "read TM1; they never change it."
    )
    required_permission = "tm1.read"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "The TM1 connection to watch."},
            "kind": {"type": "string", "enum": list(KINDS)},
            "params": {"type": "object", "description": "The kind's parameters (see the description)."},
            "rationale": {"type": "string", "description": "What the user asked for, in their words."},
        },
        "required": ["connection_id", "kind", "rationale"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _authorize(db, user_id, self.required_permission)
        rule = await monitoring_rules_service.create(
            db,
            organization_id=organization_id,
            user_id=user_id,
            connection_id=uuid.UUID(str(kwargs["connection_id"])),
            kind=str(kwargs["kind"]),
            params=kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {},
            source="ai",
            rationale=str(kwargs.get("rationale") or ""),
        )
        return json.dumps({
            "rule_id": str(rule.id),
            "status": rule.status,
            "rule": describe(rule.kind, rule.params),
            "note": (
                "Saved as a proposal. Tell the user to turn it on on the Alerts page; "
                "it is not checked until they do. It only reads TM1."
            ),
        })


class GetMonitorAlertsTool(Tool):

    name = "get_monitor_alerts"
    description = (
        "Read monitoring alerts — failed processes, slow runs, dimension "
        "growth, security, model and deployment changes — that rules have "
        "raised, open ones by default, optionally for one connection. Use "
        "when the user asks what is wrong, what changed, or about alerts."
    )
    required_permission = "monitoring.view"
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": {"type": "string", "description": "Optional: only this connection."},
            "status": {"type": "string", "enum": ["open", "acknowledged", "resolved"]},
        },
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _authorize(db, user_id, self.required_permission)
        connection_id = kwargs.get("connection_id")
        alerts = await monitoring_rules_service.list_alerts(
            db, organization_id, user_id,
            status=str(kwargs.get("status") or "open"),
            connection_id=uuid.UUID(str(connection_id)) if connection_id else None,
            limit=50,
        )
        return json.dumps(
            {
                "alerts": [
                    {"severity": a.severity, "title": a.title, "detail": a.detail, "status": a.status,
                     "fired_at": a.fired_at, "connection_id": str(a.connection_id)}
                    for a in alerts
                ],
                "evidence": "Raised by monitoring rules from TM1's message log, element counts, "
                            "security and PA-Copilot's own change records.",
            },
            default=str,
        )
