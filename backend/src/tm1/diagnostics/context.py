"""What surrounds a failed process: what runs it, and what changed lately.

A failure that began on Tuesday usually has a Tuesday cause. Two records
PA-Copilot keeps answer "what changed?" without anyone remembering:

* the extraction history (src/tm1/metadata/history.py) — objects and
  dependencies that disappeared from the model, filtered to the ones this
  process touches;
* its own change records — edits to this process applied through approval.

And the dependency map answers who is affected: the chores and processes
that run this one.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException
from src.database.models.tm1_change import TM1Change
from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.history import list_extractions

# How far back PA-Copilot's own changes to the process are listed.
RECENT_CHANGE_DAYS = 30


async def runners(
    db: AsyncSession, connection_id: uuid.UUID, organization_id: uuid.UUID, process_name: str
) -> list[dict] | None:
    """Chores and processes that run this one, directly or through a
    caller. None when the process is not in the dependency map."""

    try:
        dependents = await dependency_analyzer.find_dependents(
            db, connection_id, organization_id, "process", process_name, max_depth=3
        )
    except NotFoundException:
        return None

    return [
        {"type": d["object_type"], "name": d["name"], "via": d["via"], "depth": d["depth"]}
        for d in dependents
        if d["object_type"] in ("chore", "process")
    ]


async def model_changes_touching(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    names: set[str],
    extractions: int = 3,
) -> list[dict]:
    """Objects and dependencies that disappeared from the model in recent
    extractions and involve any of `names` — the ones that break a process."""

    wanted = {n.lower() for n in names if n}
    found: list[dict] = []

    for record in await list_extractions(db, connection_id, organization_id, extractions):
        changes = record.changes or {}

        if record.status != "succeeded" or changes.get("first"):
            continue

        for obj in changes.get("objects_removed", []):
            if obj["name"].lower() in wanted or obj["name"].partition(":")[0].lower() in wanted:
                found.append({
                    "extraction": record.started_at.isoformat(),
                    "removed_object": f"{obj['type']} {obj['name']}",
                })

        for edge in changes.get("relationships_removed", []):
            ends = {edge["from"].partition(":")[2].lower(), edge["to"].partition(":")[2].lower()}
            if ends & wanted:
                found.append({
                    "extraction": record.started_at.isoformat(),
                    "removed_dependency": f"{edge['from']} {edge['relationship']} {edge['to']}",
                })

    return found


async def recent_changes(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    process_name: str,
) -> list[dict]:
    """Changes to this process applied (or attempted) through PA-Copilot
    in the last RECENT_CHANGE_DAYS days, newest first."""

    since = datetime.now(timezone.utc) - timedelta(days=RECENT_CHANGE_DAYS)
    rows = (
        await db.execute(
            select(TM1Change)
            .where(
                TM1Change.connection_id == connection_id,
                TM1Change.organization_id == organization_id,
                func.lower(TM1Change.target_name) == process_name.lower(),
                TM1Change.executed_at.is_not(None),
                TM1Change.executed_at >= since,
            )
            .order_by(TM1Change.executed_at.desc())
            .limit(10)
        )
    ).scalars()

    return [
        {
            "change_id": str(c.id),
            "type": c.change_type,
            "status": c.status,
            "executed_at": c.executed_at.isoformat() if c.executed_at else None,
            "rolled_back_at": c.rolled_back_at.isoformat() if c.rolled_back_at else None,
        }
        for c in rows
    ]
