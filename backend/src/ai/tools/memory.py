"""Engineering memory, for the agents.

Approved memories are already in every conversation's context; these tools
let an agent search them for one object, and suggest a new one when it
learns something the team should keep — a suggestion only, which a person
must approve before any conversation sees it.
"""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.services.engineering_memory_service import KINDS, OBJECT_TYPES, engineering_memory_service
from src.tm1.service import tm1_integration_service


async def _authorize(db: AsyncSession, user_id: uuid.UUID, permission: str) -> None:
    if not await auth_repository.user_has_permission(db, user_id, permission):
        raise PermissionDeniedException(f"Missing permission: {permission}")


class SearchEngineeringMemoryTool(Tool):

    name = "search_engineering_memory"
    description = (
        "Search the organization's approved engineering memory — conventions, "
        "run sequences, cautions and known issues people have recorded about "
        "the TM1 model — by object name or text. Use before changing or "
        "explaining an object, to find what the team already knows about it. "
        "Results are organization knowledge, not live TM1 evidence."
    )
    required_permission = "knowledge.read"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "An object name or words to look for."},
            "connection_id": {"type": "string", "description": "Optional: also the memory about this connection."},
        },
        "required": ["query"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _authorize(db, user_id, self.required_permission)
        connection_id = kwargs.get("connection_id")
        memories = await engineering_memory_service.list(
            db,
            organization_id,
            status="approved",
            connection_id=uuid.UUID(str(connection_id)) if connection_id else None,
            query=str(kwargs.get("query") or ""),
            limit=25,
        )
        return json.dumps(
            {
                "memories": [
                    {
                        "kind": m.kind,
                        "about": f"{m.object_type} {m.object_name}" if m.object_name else None,
                        "text": m.text,
                        "version": m.version,
                        "approved_at": m.decided_at,
                    }
                    for m in memories
                ],
                "evidence": "Organization knowledge approved by people — not read from TM1.",
            },
            default=str,
        )


class ProposeEngineeringMemoryTool(Tool):

    name = "propose_engineering_memory"
    description = (
        "Suggest a fact for the organization's engineering memory when the "
        "conversation establishes something the team should keep: a run "
        "sequence, a naming convention, a caution about an object, a known "
        "issue. It is saved as a PROPOSAL only — no conversation sees it until "
        "a person with knowledge rights approves it on the Engineering Memory "
        "page. Propose only what the user stated or the live evidence showed, "
        "with that evidence as the rationale; never a guess."
    )
    required_permission = "knowledge.read"
    input_schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "text": {"type": "string", "description": "The fact, in one or two sentences."},
            "rationale": {"type": "string", "description": "What the user said, or what was seen in TM1, that shows it."},
            "connection_id": {"type": "string", "description": "The TM1 connection it is about, if any."},
            "object_type": {"type": "string", "enum": list(OBJECT_TYPES)},
            "object_name": {"type": "string"},
        },
        "required": ["kind", "text", "rationale"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await _authorize(db, user_id, self.required_permission)
        connection_id = kwargs.get("connection_id")
        if connection_id:
            # The user's own or a shared connection only (the dispatcher has
            # already checked; this keeps the tool safe on its own).
            await tm1_integration_service.get_connection(
                db, uuid.UUID(str(connection_id)), organization_id, user_id=user_id
            )
        memory = await engineering_memory_service.create(
            db,
            organization_id=organization_id,
            user_id=user_id,
            kind=str(kwargs["kind"]),
            text=str(kwargs["text"]),
            source="ai",
            connection_id=uuid.UUID(str(connection_id)) if connection_id else None,
            object_type=kwargs.get("object_type"),
            object_name=kwargs.get("object_name"),
            rationale=str(kwargs.get("rationale") or ""),
        )
        return json.dumps(
            {
                "memory_id": str(memory.id),
                "status": memory.status,
                "note": (
                    "Saved as a proposal. It is not used in any conversation until a "
                    "person approves it on the Engineering Memory page."
                ),
            }
        )
