"""Extraction history: when the model was read, and what changed since.

extract_metadata rebuilds the dependency graph from scratch, so the graph
alone cannot say what changed. Reading the graph's objects and edges just
before and just after an extraction, by name rather than by row id (ids are
new every time), gives exactly that: the cubes, processes, views and
dependencies that appeared or disappeared since the extraction before.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_extraction import TM1Extraction
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.tm1.metadata.extractor import ExtractionSummary, extract_metadata

# Names kept per list on a history row. Counts are always exact.
MAX_LISTED_CHANGES = 200

# Older than this, a dependency answer says the map may be out of date.
STALE_AFTER_DAYS = 7


async def graph_keys(
    db: AsyncSession, connection_id: uuid.UUID
) -> tuple[set[tuple[str, str]], set[tuple[str, str, str, str, str]]]:
    """The graph by name: {(type, name)} and {(from_type, from_name,
    relationship, to_type, to_name)}."""

    # Two plain queries rather than a self-join: the per-organization query
    # filter (src/database/tenancy.py) does not compose with aliased joins.
    names = {
        row.id: (row.object_type, row.name)
        for row in (
            await db.execute(
                select(TM1Object.id, TM1Object.object_type, TM1Object.name).where(
                    TM1Object.connection_id == connection_id
                )
            )
        ).all()
    }
    objects = set(names.values())

    edges = set()
    for row in (
        await db.execute(
            select(
                TM1Relationship.from_object_id,
                TM1Relationship.relationship_type,
                TM1Relationship.to_object_id,
            ).where(TM1Relationship.connection_id == connection_id)
        )
    ).all():
        source, target = names.get(row.from_object_id), names.get(row.to_object_id)
        if source and target:
            edges.add((*source, row.relationship_type, *target))

    return objects, edges


def _object_entries(keys) -> list[dict]:
    return [{"type": t, "name": n} for t, n in sorted(keys)][:MAX_LISTED_CHANGES]


def _edge_entries(keys) -> list[dict]:
    return [
        {"from": f"{ft}:{fn}", "relationship": rel, "to": f"{tt}:{tn}"}
        for ft, fn, rel, tt, tn in sorted(keys)
    ][:MAX_LISTED_CHANGES]


def diff_graphs(before, after) -> dict:
    """What changed between two graphs given by graph_keys."""

    objects_before, edges_before = before
    objects_after, edges_after = after

    added_objects = objects_after - objects_before
    removed_objects = objects_before - objects_after
    added_edges = edges_after - edges_before
    removed_edges = edges_before - edges_after

    return {
        # Nothing to compare against: every object would read as "added".
        "first": not objects_before,
        "counts": {
            "objects_added": len(added_objects),
            "objects_removed": len(removed_objects),
            "relationships_added": len(added_edges),
            "relationships_removed": len(removed_edges),
        },
        "objects_added": [] if not objects_before else _object_entries(added_objects),
        "objects_removed": _object_entries(removed_objects),
        "relationships_added": [] if not objects_before else _edge_entries(added_edges),
        "relationships_removed": _edge_entries(removed_edges),
    }


async def run_extraction(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    trigger: str,
    triggered_by: uuid.UUID | None = None,
) -> tuple[ExtractionSummary, TM1Extraction]:
    """Extract the model, and record the extraction with what changed."""

    started_at = datetime.now(timezone.utc)
    before = await graph_keys(db, connection_id)

    summary = await extract_metadata(db, connection_id, organization_id)

    after = await graph_keys(db, connection_id)
    record = TM1Extraction(
        connection_id=connection_id,
        organization_id=organization_id,
        trigger=trigger,
        triggered_by=triggered_by,
        status="succeeded",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        object_count=len(after[0]),
        relationship_count=len(after[1]),
        unresolved_references=summary.unresolved_references,
        changes=diff_graphs(before, after),
    )
    db.add(record)
    await db.flush()

    return summary, record


async def record_failure(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    trigger: str,
    started_at: datetime,
    error: str,
) -> TM1Extraction:
    """A failed extraction leaves the previous graph in place (its
    transaction rolled back); this row says it was tried and why it failed."""

    record = TM1Extraction(
        connection_id=connection_id,
        organization_id=organization_id,
        trigger=trigger,
        status="failed",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        error_message=error[:2000],
    )
    db.add(record)
    await db.flush()
    return record


async def graph_freshness(
    db: AsyncSession, connection_id: uuid.UUID
) -> dict:
    """How current the dependency graph is, for every answer drawn from it.

    The graph is a snapshot: a process created or changed in TM1 since the
    last extraction is not in it. Saying when it was taken lets the answer
    say "as of", and say plainly when that is too old to trust.
    """

    extracted_at = (
        await db.execute(
            select(func.max(TM1Object.extracted_at)).where(
                TM1Object.connection_id == connection_id
            )
        )
    ).scalar_one_or_none()

    if extracted_at is None:
        return {"extracted_at": None, "note": "No metadata extraction yet."}

    age_days = (datetime.now(timezone.utc) - extracted_at).total_seconds() / 86400
    result = {"extracted_at": extracted_at.isoformat(), "age_days": round(age_days, 1)}

    if age_days > STALE_AFTER_DAYS:
        result["note"] = (
            f"The dependency map is {int(age_days)} days old; objects changed "
            "since then are not reflected. Re-run metadata extraction for a "
            "current answer."
        )

    return result


async def list_extractions(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    limit: int = 20,
) -> list[TM1Extraction]:
    return list(
        (
            await db.execute(
                select(TM1Extraction)
                .where(
                    TM1Extraction.connection_id == connection_id,
                    TM1Extraction.organization_id == organization_id,
                )
                .order_by(TM1Extraction.started_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def last_successful(
    db: AsyncSession, connection_id: uuid.UUID, organization_id: uuid.UUID
) -> TM1Extraction | None:
    return (
        await db.execute(
            select(TM1Extraction)
            .where(
                TM1Extraction.connection_id == connection_id,
                TM1Extraction.organization_id == organization_id,
                TM1Extraction.status == "succeeded",
            )
            .order_by(TM1Extraction.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# The daily refresh stops starting new extractions after this long, so a
# run always finishes inside the platform's 300-second request limit with
# room for the extraction already in progress.
REFRESH_START_BUDGET_SECONDS = 150

# A connection extracted more recently than this is left alone.
REFRESH_MIN_AGE_HOURS = 20


async def refresh_due_connections() -> dict:
    """Re-extract every connection whose dependency map is a day old.

    Only connections someone has extracted at least once: a connection that
    was never mapped was never asked for, and extracting it uninvited would
    read a server no one pointed this feature at. Stalest first, each in its
    own transaction, so one unreachable server costs its own refresh and not
    the others'. A failure leaves the previous map in place and is recorded.
    """

    import time

    from src.database.models.tm1_connection import TM1Connection
    from src.database.session import AsyncSessionLocal

    started = time.monotonic()
    cutoff = datetime.now(timezone.utc).timestamp() - REFRESH_MIN_AGE_HOURS * 3600

    async with AsyncSessionLocal() as db:
        last_extracted = (
            select(
                TM1Object.connection_id.label("connection_id"),
                func.max(TM1Object.extracted_at).label("extracted_at"),
            )
            .group_by(TM1Object.connection_id)
            .subquery()
        )
        due = (
            await db.execute(
                select(TM1Connection.id, TM1Connection.organization_id, last_extracted.c.extracted_at)
                .join(last_extracted, last_extracted.c.connection_id == TM1Connection.id)
                .where(TM1Connection.is_active.is_(True))
                .order_by(last_extracted.c.extracted_at.asc())
            )
        ).all()

    refreshed, failed, skipped = [], [], 0

    for connection_id, organization_id, extracted_at in due:
        if extracted_at.timestamp() > cutoff:
            continue
        if time.monotonic() - started > REFRESH_START_BUDGET_SECONDS:
            skipped += 1
            continue

        attempt_started = datetime.now(timezone.utc)
        try:
            async with AsyncSessionLocal() as db:
                await run_extraction(db, connection_id, organization_id, trigger="schedule")
                await db.commit()
            refreshed.append(str(connection_id))
        except Exception as exc:  # noqa: BLE001 - one server's failure is recorded, not fatal
            async with AsyncSessionLocal() as db:
                await record_failure(
                    db,
                    connection_id,
                    organization_id,
                    trigger="schedule",
                    started_at=attempt_started,
                    error=getattr(exc, "message", None) or type(exc).__name__,
                )
                await db.commit()
            failed.append(str(connection_id))

    return {"refreshed": len(refreshed), "failed": len(failed), "deferred": skipped}
