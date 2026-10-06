"""How long processes take, and when that suddenly changes.

TM1 writes a line to its message log each time a process finishes, with
how long it ran. That log rolls over, so on its own it cannot answer "is
this slower than usual?". Collecting those lines into tm1_process_runs —
and the runs PA-Copilot itself started — builds the history that can.

A regression is reported only when it is clearly one: the newest run took
more than REGRESSION_FACTOR times the median of the runs before it in the
window, at least MIN_PREVIOUS_RUNS of them, and at least
MIN_EXTRA_SECONDS longer in absolute terms (a 2-second load taking 5 is
not news). The median, not the mean, so one earlier outlier cannot hide or
fake a regression.
"""

import re
import statistics
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from TM1py import TM1Service

from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_health import TM1ProcessRun
from src.tm1.resilience import call_with_resilience
from src.tm1.services.log_service import classify_run_message

# Message-log lines read per collection. A busy server writes a few hundred
# process lines a day; collected daily, this keeps up with plenty to spare.
COLLECT_ROWS = 2000
WINDOW_DAYS = 30
REGRESSION_FACTOR = 2.0
MIN_PREVIOUS_RUNS = 3
MIN_EXTRA_SECONDS = 30.0

_ELAPSED = re.compile(r"elapsed time\s+([0-9]+(?:\.[0-9]+)?)\s*seconds", re.IGNORECASE)
_PROCESS_NAME = re.compile(r'process\s+"([^"]+)"', re.IGNORECASE)
_FINISHED = ("succeeded", "aborted", "completed_with_errors", "quit")


def _timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_runs(entries: list[dict]) -> list[dict]:
    """Every finished process run in a batch of message-log entries."""

    runs = []
    for entry in entries:
        message = str(entry.get("Message") or "")
        name = _PROCESS_NAME.search(message)
        outcome = classify_run_message(message)
        finished_at = _timestamp(entry.get("TimeStamp"))

        if not name or outcome not in _FINISHED or finished_at is None:
            continue

        elapsed = _ELAPSED.search(message)
        runs.append({
            "process_name": name.group(1),
            "finished_at": finished_at,
            "elapsed_seconds": float(elapsed.group(1)) if elapsed else None,
            "outcome": outcome,
        })
    return runs


async def _store(db: AsyncSession, connection_id, organization_id, runs: list[dict], source: str) -> int:
    if not runs:
        return 0
    result = await db.execute(
        insert(TM1ProcessRun)
        .values([
            {
                "id": uuid.uuid4(),
                "connection_id": connection_id,
                "organization_id": organization_id,
                "source": source,
                **run,
            }
            for run in runs
        ])
        .on_conflict_do_nothing(constraint="uq_tm1_process_runs_run")
        .returning(TM1ProcessRun.id)
    )
    return len(result.all())


async def collect_runs(
    db: AsyncSession,
    client: TM1Service,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> int:
    """Add the runs TM1's message log and PA-Copilot's own run changes
    know about. Returns how many were new."""

    entries = await call_with_resilience(
        connection_id,
        client.server.get_message_log_entries,
        reverse=True,
        top=COLLECT_ROWS,
        logger="TM1.Process",
    )
    added = await _store(db, connection_id, organization_id, parse_runs(entries or []), "message_log")

    ours = (
        await db.execute(
            select(TM1Change).where(
                TM1Change.connection_id == connection_id,
                TM1Change.organization_id == organization_id,
                TM1Change.change_type == "run_process",
                TM1Change.executed_at.is_not(None),
                TM1Change.execution_result.is_not(None),
            )
        )
    ).scalars()
    pa_runs = []
    for change in ours:
        result = change.execution_result or {}
        if result.get("status") == "NotStarted":
            continue
        duration = result.get("duration_ms")
        pa_runs.append({
            "process_name": change.target_name,
            "finished_at": change.executed_at,
            "elapsed_seconds": duration / 1000 if isinstance(duration, (int, float)) else None,
            "outcome": "succeeded" if result.get("success") else "aborted",
        })
    added += await _store(db, connection_id, organization_id, pa_runs, "pa_copilot")

    return added


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    if minutes < 90:
        return f"{minutes} min {rest} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


async def report(
    db: AsyncSession, connection_id: uuid.UUID, organization_id: uuid.UUID
) -> dict:
    """Regressions, the slowest processes, and recent failures, from the
    collected history of the last WINDOW_DAYS days."""

    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    # Only the four columns the analysis reads: a busy server logs tens of
    # thousands of runs a month, and loading each as a full ORM object made
    # this the slowest part of the Command Center.
    rows = (
        await db.execute(
            select(
                TM1ProcessRun.process_name,
                TM1ProcessRun.finished_at,
                TM1ProcessRun.elapsed_seconds,
                TM1ProcessRun.outcome,
            )
            .where(
                TM1ProcessRun.connection_id == connection_id,
                TM1ProcessRun.organization_id == organization_id,
                TM1ProcessRun.finished_at >= since,
            )
            .order_by(TM1ProcessRun.finished_at.asc())
        )
    ).all()

    by_process: dict[str, list] = {}
    for row in rows:
        by_process.setdefault(row.process_name, []).append(row)

    regressions, typical, failures = [], [], []
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    for name, runs in by_process.items():
        timed = [r for r in runs if r.elapsed_seconds is not None]

        if timed:
            typical.append({
                "process": name,
                "median_seconds": round(statistics.median(r.elapsed_seconds for r in timed), 1),
                "runs": len(timed),
            })

        if len(timed) > MIN_PREVIOUS_RUNS:
            latest, previous = timed[-1], timed[:-1]
            median = statistics.median(r.elapsed_seconds for r in previous)
            if (
                median > 0
                and latest.elapsed_seconds > REGRESSION_FACTOR * median
                and latest.elapsed_seconds - median >= MIN_EXTRA_SECONDS
            ):
                increase = (latest.elapsed_seconds - median) / median * 100
                regressions.append({
                    "process": name,
                    "usual_seconds": round(median, 1),
                    "latest_seconds": round(latest.elapsed_seconds, 1),
                    "latest_at": latest.finished_at.isoformat(),
                    "increase_percent": round(increase),
                    "based_on_runs": len(previous),
                    "summary": (
                        f"{name} normally runs in {_duration(median)} (median of "
                        f"{len(previous)} runs). Latest run: {_duration(latest.elapsed_seconds)} "
                        f"on {latest.finished_at:%Y-%m-%d %H:%M}. Regression: +{increase:.0f}%."
                    ),
                })

        failed = [r for r in runs if r.finished_at >= week_ago and r.outcome in ("aborted", "completed_with_errors")]
        if failed:
            failures.append({
                "process": name,
                "failed_runs_7_days": len(failed),
                "last_failed_at": failed[-1].finished_at.isoformat(),
                "outcome": failed[-1].outcome,
            })

    regressions.sort(key=lambda r: -r["increase_percent"])
    typical.sort(key=lambda t: -t["median_seconds"])
    failures.sort(key=lambda f: -f["failed_runs_7_days"])

    return {
        "window_days": WINDOW_DAYS,
        "runs_known": len(rows),
        "processes_seen": len(by_process),
        "regressions": regressions,
        "slowest": typical[:10],
        "failures_7_days": failures,
        "rule": (
            f"A regression is a latest run over {REGRESSION_FACTOR:g}x the median of at "
            f"least {MIN_PREVIOUS_RUNS} earlier runs in {WINDOW_DAYS} days, and at least "
            f"{MIN_EXTRA_SECONDS:.0f} s longer."
        ),
        "not_covered": [
            "Memory and CPU per process: TM1 REST does not report them per run",
            "Runs older than the message log PA-Copilot has collected",
        ],
    }
