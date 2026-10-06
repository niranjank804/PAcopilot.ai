"""Promoting a proven change up the environments: DEV -> QA -> PROD.

A change earns promotion by having been applied and verified where it is,
and not rolled back. Promotion does not copy that success across: it makes
a new draft on the next environment's server from the same content, and
that draft is compiled, impact-analysed and fingerprinted against *that*
server, then approved under *that* environment's rules (src/tm1/governance.py
— on PROD, by a second person). The two are linked, so the package can show
the whole road: where the change has been, who approved it, what was
verified, and that the content did not change on the way.

Process runs are not promoted. A run is an operation on one server's data,
not a change to its model.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationException
from src.database.models.tm1_change import TM1Change
from src.repositories.tm1_change_repository import tm1_change_repository
from src.repositories.user_repository import user_repository
from src.tm1 import governance
from src.tm1.deployment.change_service import change_service
from src.tm1.service import tm1_integration_service

NEXT_ENVIRONMENT = {"dev": "qa", "qa": "prod"}
PROMOTABLE = ("update_rules", "create_process", "update_process", "delete_process")
# A chain longer than DEV -> QA -> PROD means something linked oddly; stop.
MAX_CHAIN = 5


def _content_hash(content: dict | None) -> str:
    return hashlib.sha256(
        json.dumps(content or {}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def promote(
    db: AsyncSession,
    source: TM1Change,
    *,
    target_connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TM1Change:
    """Draft `source` on the next environment's connection."""

    if source.change_type == "create_view":
        raise ValidationException(
            "A new view is not promoted: views made for review or evidence belong "
            "to the server they were made on. Propose it on the target connection "
            "instead."
        )
    if source.change_type not in PROMOTABLE:
        raise ValidationException(
            "A process run or a cell write is not promoted: it acts on one "
            "server's data. Propose it on the target connection instead."
        )
    if source.status != "executed" or source.rolled_back_at is not None:
        raise ValidationException(
            "Only a change that was applied and verified here, and not rolled "
            "back, can be promoted."
        )

    source_connection = await tm1_integration_service.get_connection(
        db, source.connection_id, organization_id
    )
    target_connection = await tm1_integration_service.get_connection(
        db, target_connection_id, organization_id
    )
    source_env = governance.environment_of(source_connection)
    target_env = governance.environment_of(target_connection)
    expected = NEXT_ENVIRONMENT.get(source_env)

    if expected is None:
        raise ValidationException("This change is already in PROD; there is nowhere to promote it.")
    if target_env != expected:
        raise ValidationException(
            f"A {source_env.upper()} change is promoted to {expected.upper()} next, "
            f"not to {target_env.upper()} ('{target_connection.name}')."
        )

    draft = await change_service.create_change(
        db,
        connection_id=target_connection.id,
        organization_id=organization_id,
        created_by=user_id,
        change_type=source.change_type,
        target_name=source.target_name,
        new_content=source.new_content,
    )
    draft.promoted_from = source.id
    return await tm1_change_repository.update(db, draft)


async def _chain(db: AsyncSession, change: TM1Change) -> list[TM1Change]:
    """The change and everything it was promoted from, oldest first."""

    chain = [change]
    while chain[0].promoted_from and len(chain) < MAX_CHAIN:
        earlier = await tm1_change_repository.get_by_id(db, chain[0].promoted_from)
        if earlier is None or earlier.organization_id != change.organization_id:
            break
        chain.insert(0, earlier)
    return chain


async def _name_of(db: AsyncSession, user_id: uuid.UUID | None, cache: dict) -> str | None:
    if user_id is None:
        return None
    if user_id not in cache:
        user = await user_repository.get_by_id(db, user_id)
        cache[user_id] = (
            f"{user.first_name} {user.last_name}".strip() or user.username if user else str(user_id)
        )
    return cache[user_id]


def _rollback_plan(change: TM1Change, connection_name: str) -> str:
    if change.change_type == "create_process":
        return (
            f"Roll back deletes the new process '{change.target_name}' from "
            f"{connection_name}."
        )
    if change.change_type == "delete_process":
        return (
            f"The process is saved before it is deleted; Roll back restores it on "
            f"{connection_name}, unless a process of that name exists again."
        )
    if change.change_type == "create_view":
        view_name = (change.new_content or {}).get("view_name")
        return (
            f"Roll back deletes the new view '{view_name}' on '{change.target_name}' "
            f"from {connection_name}, and refuses if the view has been changed since."
        )
    if change.change_type == "write_cells":
        return (
            f"The current values of the cells are saved when the change is applied. "
            f"Roll back writes them back on {connection_name}, and refuses if anyone "
            "has written those cells since."
        )
    what = "rules" if change.change_type == "update_rules" else "process"
    return (
        f"The current {what} of '{change.target_name}' on {connection_name} are "
        "saved when the change is applied. Roll back restores them, and refuses "
        "if someone has edited them since, so later work is never overwritten."
    )


async def package(db: AsyncSession, change: TM1Change) -> dict:
    """Everything an approver needs to decide on a change, in one document:
    what and where, the road it took, the evidence, the diff and impact,
    and how to undo it."""

    chain = await _chain(db, change)
    names: dict = {}
    connections: dict = {}

    async def connection_of(c: TM1Change):
        if c.connection_id not in connections:
            connections[c.connection_id] = await tm1_integration_service.get_connection(
                db, c.connection_id, c.organization_id
            )
        return connections[c.connection_id]

    target = await connection_of(change)
    target_env = governance.environment_of(target)
    content_hash = _content_hash(change.new_content)

    stages = []
    for c in chain:
        conn = await connection_of(c)
        stages.append({
            "change_id": str(c.id),
            "environment": governance.environment_of(conn).upper(),
            "connection": conn.name,
            "status": c.status,
            "requested_by": await _name_of(db, c.created_by, names),
            "requested_at": c.created_at,
            "approved_by": await _name_of(db, c.executed_by, names),
            "approved_at": c.executed_at,
            "rolled_back_at": c.rolled_back_at,
            "verified": c.status == "executed" and c.rolled_back_at is None,
            "same_content": _content_hash(c.new_content) == content_hash,
            "checks": c.checks or [],
        })

    preview = await change_service.get_change_preview(db, change)
    two_person = target_env == "prod"

    return {
        "manifest": {
            "change_id": str(change.id),
            "change_type": change.change_type,
            "object": change.target_name,
            "target_connection": target.name,
            "target_environment": target_env.upper(),
            "status": change.status,
            "content_sha256": content_hash,
            "generated_at": datetime.now(timezone.utc),
        },
        "stages": stages,
        "evidence": {
            "verified_in": [s["environment"] for s in stages[:-1] if s["verified"]],
            "content_unchanged_since_first_stage": all(s["same_content"] for s in stages),
            "checks_here": change.checks or [],
        },
        "diff": {"current": preview["current"], "proposed": preview["proposed"]},
        "impact": change.impact or [],
        "approval_rule": (
            f"Needs the '{governance.DEPLOY_PERMISSION[target_env]}' permission"
            + (", and someone other than the requester" if two_person else "")
            + (", and 'tm1.execute' for a run" if change.change_type == "run_process" else "")
            + "."
        ),
        "rollback_plan": _rollback_plan(change, target.name),
    }
