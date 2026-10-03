"""The model health score: 100, minus points for what was found.

A score is only useful if anyone can check it. So it is arithmetic, not a
judgment: each category costs a fixed number of points per item, up to a
cap so one category cannot sink the whole model, and every point taken off
lists the objects that cost it.

| Category                               | Points each | Cap |
|----------------------------------------|-------------|-----|
| Critical rule findings                 | 10          | 40  |
| Process errors (won't compile or run)  | 5           | 25  |
| Rule warnings                          | 2           | 15  |
| Performance regressions                | 3           | 15  |
| Processes that failed in the last week | 2           | 10  |
| Other process findings                 | 0.5         | 10  |
| Unused objects                         | 0.5         | 5   |

Grade: A 90+, B 75+, C 60+, D 40+, F below.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.tm1_health import TM1HealthScan
from src.tm1.health import performance
from src.tm1.metadata import dependency_analyzer
from src.tm1.metadata.history import graph_freshness
from src.tm1.service import tm1_integration_service

# (key, label, points per item, cap)
CATEGORIES = [
    ("critical_rule_findings", "Critical rule findings", 10, 40),
    ("process_errors", "Process errors (won't compile or run)", 5, 25),
    ("rule_warnings", "Rule warnings", 2, 15),
    ("regressions", "Performance regressions", 3, 15),
    ("failed_processes", "Processes that failed in the last 7 days", 2, 10),
    ("process_issues", "Other process findings", 0.5, 10),
    ("unused_objects", "Unused objects", 0.5, 5),
]
MAX_EVIDENCE = 15
MAX_STORED_FINDINGS = 25


def grade(score: int) -> str:
    for threshold, letter in ((90, "A"), (75, "B"), (60, "C"), (40, "D")):
        if score >= threshold:
            return letter
    return "F"


def compute(counts: dict[str, int], evidence: dict[str, list[str]]) -> tuple[int, list[dict]]:
    """The score and the deduction behind each point, from counts per
    category. Pure: the same counts always give the same score."""

    deductions = []
    total = 0.0
    for key, label, each, cap in CATEGORIES:
        count = counts.get(key, 0)
        points = min(count * each, cap)
        total += points
        deductions.append({
            "category": key,
            "label": label,
            "count": count,
            "points": round(points, 1),
            "points_each": each,
            "cap": cap,
            "evidence": evidence.get(key, [])[:MAX_EVIDENCE],
        })
    return max(0, round(100 - total)), deductions


async def run_health_scan(
    db: AsyncSession,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    trigger: str,
) -> tuple[TM1HealthScan, dict]:
    """Collect recent runs, audit rules and processes, read the dependency
    map, score it all, and keep the scan. Returns the scan and the
    performance report it used."""

    # Imported here: the audits live with the agent tool that also runs
    # them on demand, which imports from this package's neighbours.
    from src.ai.tools.tm1.health import CONCURRENCY, RunModelHealthCheckTool

    connection, client = await tm1_integration_service.connect(db, connection_id, organization_id)

    await performance.collect_runs(db, client, connection.id, organization_id)
    perf = await performance.report(db, connection.id, organization_id)

    auditor = RunModelHealthCheckTool()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    cube_report, process_report = await asyncio.gather(
        auditor._audit_rules(client, connection.id, semaphore),
        auditor._audit_processes(client, connection.id, semaphore, None),
    )

    notes = []
    if (await graph_freshness(db, connection.id))["extracted_at"] is None:
        unused = []
        notes.append("Unused objects not counted: no dependency map yet (run metadata extraction).")
    else:
        unused = await dependency_analyzer.find_unused_objects(db, connection.id, organization_id)

    cubes = cube_report["cubes"]
    processes = process_report["processes"]
    counts = {
        "critical_rule_findings": sum(c["critical"] for c in cubes),
        "rule_warnings": sum(c["warning"] for c in cubes),
        "process_errors": sum(p["errors"] for p in processes),
        "process_issues": sum(p["finding_count"] - p["errors"] for p in processes),
        "unused_objects": len(unused),
        "failed_processes": len(perf["failures_7_days"]),
        "regressions": len(perf["regressions"]),
    }
    evidence = {
        "critical_rule_findings": [f"cube {c['cube']}: {c['critical']}" for c in cubes if c["critical"]],
        "rule_warnings": [f"cube {c['cube']}: {c['warning']}" for c in cubes if c["warning"]],
        "process_errors": [f"process {p['process']}: {p['errors']}" for p in processes if p["errors"]],
        "process_issues": [
            f"process {p['process']}: {p['finding_count'] - p['errors']}"
            for p in processes if p["finding_count"] - p["errors"] > 0
        ],
        "unused_objects": [f"{u['object_type']} {u['name']}" for u in unused],
        "failed_processes": [
            f"{f['process']}: {f['failed_runs_7_days']} failed run(s), last {f['last_failed_at'][:16]}"
            for f in perf["failures_7_days"]
        ],
        "regressions": [r["summary"] for r in perf["regressions"]],
    }
    if cube_report["truncated"] or process_report["truncated"]:
        notes.append(
            f"Large model: {cube_report['analysed']} cubes and {process_report['analysed']} "
            "processes were analysed, not all of them."
        )

    score, deductions = compute(counts, evidence)
    scan = TM1HealthScan(
        connection_id=connection.id,
        organization_id=organization_id,
        trigger=trigger,
        scanned_at=datetime.now(timezone.utc),
        score=score,
        grade=grade(score),
        deductions=deductions,
        totals={
            **counts,
            "cubes_analysed": cube_report["analysed"],
            "processes_analysed": process_report["analysed"],
            "runs_known": perf["runs_known"],
            "notes": notes,
        },
        findings={
            "rules": cubes[:MAX_STORED_FINDINGS],
            "processes": processes[:MAX_STORED_FINDINGS],
        },
    )
    db.add(scan)
    await db.flush()
    return scan, perf


async def recent_scans(
    db: AsyncSession, connection_id: uuid.UUID, organization_id: uuid.UUID, limit: int = 10
) -> list[TM1HealthScan]:
    return list(
        (
            await db.execute(
                select(TM1HealthScan)
                .where(
                    TM1HealthScan.connection_id == connection_id,
                    TM1HealthScan.organization_id == organization_id,
                )
                .order_by(TM1HealthScan.scanned_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


# Like the dependency-map refresh: stop starting scans after this long so
# the run ends within the platform's request limit.
SCAN_START_BUDGET_SECONDS = 150
SCAN_MIN_AGE_HOURS = 20


async def scan_due_connections() -> dict:
    """Re-scan each connection someone has scanned before, once a day,
    stalest first, each in its own transaction. Connections never scanned
    were never asked for and are left alone."""

    import time

    from sqlalchemy import func

    from src.database.models.tm1_connection import TM1Connection
    from src.database.session import AsyncSessionLocal

    started = time.monotonic()
    cutoff = datetime.now(timezone.utc).timestamp() - SCAN_MIN_AGE_HOURS * 3600

    async with AsyncSessionLocal() as db:
        last = (
            select(TM1HealthScan.connection_id.label("connection_id"),
                   func.max(TM1HealthScan.scanned_at).label("scanned_at"))
            .group_by(TM1HealthScan.connection_id)
            .subquery()
        )
        due = (
            await db.execute(
                select(TM1Connection.id, TM1Connection.organization_id, last.c.scanned_at)
                .join(last, last.c.connection_id == TM1Connection.id)
                .where(TM1Connection.is_active.is_(True))
                .order_by(last.c.scanned_at.asc())
            )
        ).all()

    scanned = failed = deferred = 0
    for connection_id, organization_id, scanned_at in due:
        if scanned_at.timestamp() > cutoff:
            continue
        if time.monotonic() - started > SCAN_START_BUDGET_SECONDS:
            deferred += 1
            continue
        try:
            async with AsyncSessionLocal() as db:
                await run_health_scan(db, connection_id, organization_id, trigger="schedule")
                await db.commit()
            scanned += 1
        except Exception:  # noqa: BLE001 - one unreachable server must not stop the rest
            failed += 1

    return {"scanned": scanned, "failed": failed, "deferred": deferred}
