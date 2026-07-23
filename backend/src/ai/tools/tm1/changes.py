import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository
from src.tm1.deployment.change_service import change_service

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

        new_content = {
            key: str(kwargs[key])
            for key in ("prolog", "metadata", "data", "epilog")
            if key in kwargs
        }

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
