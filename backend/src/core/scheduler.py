"""Minimal in-process periodic task runner.

PA-Copilot had nowhere for recurring work to live. The consequence was
already visible: the stale-execution reaper ran only when a worker
happened to poll, so an organization with no worker running never had
its abandoned executions reclaimed at all.

This is deliberately the smallest thing that fixes that, not a job
queue. No Celery, no Redis, no broker — those are real infrastructure
decisions and this codebase has no message broker to build on.

## The problem this has to solve

`gunicorn --workers 2` means two processes, each importing this module
and each starting its own loop. Naively that runs every task twice, and
a reaper running twice concurrently can time out an execution another
copy just legitimately claimed.

The fix is a **Postgres advisory lock**. `pg_try_advisory_lock` is
non-blocking and session-scoped: exactly one worker acquires it, the
others skip that tick and try again later. It needs no table, no
migration and no cleanup — if the holding process dies, its session ends
and Postgres releases the lock automatically. That last property is why
an advisory lock beats a "scheduler_leader" row, which would need
heartbeat and expiry logic of its own.

## Deliberate limitations

* **Not durable.** A task missed while every process was down is simply
  missed; there is no catch-up. Fine for sweeps that are idempotent and
  run often, wrong for anything that must happen exactly once at a
  specific time. The report scheduler will need real infrastructure —
  this is explicitly not that.
* **Free-tier hosts sleep.** Where the web service spins down on idle,
  nothing runs until a request wakes it.
* **Best-effort intervals.** A long task delays its own next run.
"""

import asyncio
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text

from src.core.config import settings
from src.core.logging import app_logger
from src.database.session import AsyncSessionLocal

#: Namespace for this application's advisory locks, so a lock id cannot
#: collide with one taken by unrelated code against the same database.
_LOCK_NAMESPACE = 0x5041_434F  # "PACO"


@dataclass
class PeriodicTask:
    name: str
    interval_seconds: float
    handler: Callable[[], Awaitable[None]]
    #: Skip the tick rather than queue it if another process holds the
    #: lock. Always true today; a task that genuinely tolerates
    #: concurrent execution can opt out.
    single_instance: bool = True


_TASKS: list[PeriodicTask] = []
_running: list[asyncio.Task] = []


def register(task: PeriodicTask) -> None:
    _TASKS.append(task)


def _lock_id(name: str) -> int:
    """Stable 32-bit id from a task name.

    crc32 rather than hash(): Python's hash is salted per process, so
    two gunicorn workers would compute *different* lock ids for the same
    task and both would acquire successfully — defeating the entire
    mechanism in a way that only shows up under multiple workers.
    """

    return zlib.crc32(name.encode("utf-8")) & 0x7FFF_FFFF


async def _run_once(task: PeriodicTask) -> None:
    """Run one tick, holding the advisory lock for its duration."""

    async with AsyncSessionLocal() as session:
        acquired = True

        if task.single_instance:
            result = await session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :id)"),
                {"ns": _LOCK_NAMESPACE, "id": _lock_id(task.name)},
            )
            acquired = bool(result.scalar())

        if not acquired:
            # Another process is on it. Not an error, and deliberately
            # not logged at info: with several workers this is the
            # common case every tick.
            app_logger.debug(f"scheduler: '{task.name}' held elsewhere")

            return

        try:
            await task.handler()
        finally:
            if task.single_instance:
                # Released explicitly rather than relying on session
                # close, so the lock is never held across a pooled
                # connection being handed to an unrelated request.
                await session.execute(
                    text("SELECT pg_advisory_unlock(:ns, :id)"),
                    {"ns": _LOCK_NAMESPACE, "id": _lock_id(task.name)},
                )
                await session.commit()


async def _loop(task: PeriodicTask) -> None:
    # Stagger the first run so several tasks (and several freshly
    # started gunicorn workers) do not all hit the database at once.
    await asyncio.sleep(min(task.interval_seconds, 10) * 0.5)

    while True:
        try:
            await _run_once(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # A failing task must never kill its own loop — that would
            # silently stop all future runs, which is worse than the
            # failure itself and much harder to notice.
            app_logger.error(
                f"scheduler: '{task.name}' raised {type(exc).__name__}"
            )

        await asyncio.sleep(task.interval_seconds)


def start() -> None:
    """Start every registered task. Safe to call once per process."""

    if not settings.SCHEDULER_ENABLED:
        app_logger.info("scheduler: disabled by configuration")

        return

    if _running:
        return

    for task in _TASKS:
        _running.append(asyncio.create_task(_loop(task), name=f"sched:{task.name}"))

    app_logger.info(f"scheduler: started {len(_running)} periodic task(s)")


async def stop() -> None:
    """Cancel every loop and wait for it to unwind."""

    for job in _running:
        job.cancel()

    for job in _running:
        try:
            await job
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    _running.clear()
