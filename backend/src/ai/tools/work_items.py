"""Work items, for the agents: read one by its reference.

"Investigate PBI #1234" then starts from what the team already has: the
description, the root cause if someone wrote it, the linked conversations
and changes and where each change is in its life. Read-only — linking and
status changes are made by people on the Team page.
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.services.work_item_service import work_item_service


class GetWorkItemTool(Tool):

    name = "get_work_item"
    description = (
        "Read a team work item by its reference (for example 'PBI #1234' or "
        "'INC-88'): its description, status, the root cause and resolution "
        "people recorded, the conversations and TM1 changes linked to it, "
        "and its timeline (fix proposed, approved, applied, rolled back). "
        "Use when the user mentions a work item or ticket reference. "
        "Records the user cannot access are listed without detail."
    )
    required_permission = "ai.chat"
    input_schema = {
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "The work item reference, e.g. 'PBI #1234'."},
        },
        "required": ["reference"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        if not await auth_repository.user_has_permission(db, user_id, self.required_permission):
            raise PermissionDeniedException(f"Missing permission: {self.required_permission}")

        reference = str(kwargs.get("reference") or "").strip()
        item = await work_item_service.find_by_reference(db, organization_id, reference) if reference else None
        if item is None:
            matches = await work_item_service.search(db, organization_id, query=reference, limit=5) if reference else []
            return json.dumps({
                "found": False,
                "reference": reference,
                "similar": [{"reference": m.reference, "title": m.title, "status": m.status} for m in matches],
            })

        timeline = await work_item_service.timeline(db, item, user_id)
        return json.dumps(
            {
                "found": True,
                "reference": item.reference,
                "title": item.title,
                "status": item.status,
                "description": item.description,
                "root_cause": item.root_cause,
                "resolution": item.resolution,
                "progress": {p["label"]: p["done"] for p in timeline["progress"]},
                "linked": [
                    {k: v for k, v in entry.items()
                     if k in ("kind", "title", "available", "status", "connection_name", "environment",
                              "owner_name", "note", "target_id")}
                    for entry in timeline["links"]
                ],
                "timeline": [
                    {"at": e["at"], "what": e["title"], "detail": e["detail"], "by": e["actor"]}
                    for e in timeline["events"]
                ],
                "evidence": "Team work item and the records linked to it, as they are now.",
            },
            default=str,
        )
