"""Periodic task runner, including the multi-process safety property.

The interesting test is `test_only_one_holder_runs_a_single_instance_task`:
`gunicorn --workers 2` means two processes each running this loop, and a
reaper running twice concurrently could time out an execution the other
copy just legitimately claimed.
"""

import asyncio

import pytest
from sqlalchemy import text

from src.core import scheduler
from src.core.scheduler import PeriodicTask, _lock_id
from src.database.session import AsyncSessionLocal


class TestLockIdentity:

    def test_lock_ids_are_stable_across_processes(self):
        """crc32, not hash().

        Python's hash() is salted per process, so two gunicorn workers
        would compute different lock ids for the same task and both
        would acquire — defeating the mechanism in a way that only
        appears under multiple workers.
        """

        assert _lock_id("report.reap_stale_executions") == _lock_id(
            "report.reap_stale_executions"
        )
        # Known value: proves it is a pure function of the name and did
        # not silently become salted.
        assert _lock_id("report.reap_stale_executions") == (
            __import__("zlib").crc32(b"report.reap_stale_executions") & 0x7FFF_FFFF
        )

    def test_different_tasks_get_different_locks(self):
        assert _lock_id("task.a") != _lock_id("task.b")

    def test_lock_id_fits_postgres_int4(self):
        # pg_try_advisory_lock(int, int) takes signed 32-bit values.
        for name in ("a", "report.reap_stale_executions", "x" * 200):
            assert 0 <= _lock_id(name) <= 0x7FFF_FFFF


class TestSingleInstanceExecution:

    @pytest.mark.asyncio
    async def test_a_task_runs_when_the_lock_is_free(self):
        calls = []

        async def handler():
            calls.append(1)

        await scheduler._run_once(
            PeriodicTask(
                name="test.free_lock", interval_seconds=1, handler=handler
            )
        )

        assert calls == [1]

    @pytest.mark.asyncio
    async def test_only_one_holder_runs_a_single_instance_task(self):
        """The property that makes two gunicorn workers safe."""

        task_name = "test.contended_lock"
        calls = []

        async def handler():
            calls.append(1)

        # Stand in for the other gunicorn worker: hold the same advisory
        # lock on a separate session for the duration.
        async with AsyncSessionLocal() as holder:
            acquired = await holder.execute(
                text("SELECT pg_try_advisory_lock(:ns, :id)"),
                {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
            )

            assert acquired.scalar() is True

            try:
                await scheduler._run_once(
                    PeriodicTask(
                        name=task_name, interval_seconds=1, handler=handler
                    )
                )

                # Skipped, not queued and not run twice.
                assert calls == []
            finally:
                await holder.execute(
                    text("SELECT pg_advisory_unlock(:ns, :id)"),
                    {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
                )
                await holder.commit()

    @pytest.mark.asyncio
    async def test_the_lock_is_released_after_a_run(self):
        """Otherwise the first tick would deadlock every later one."""

        task_name = "test.release_after_run"

        async def handler():
            return None

        await scheduler._run_once(
            PeriodicTask(name=task_name, interval_seconds=1, handler=handler)
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :id)"),
                {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
            )

            assert result.scalar() is True, "lock was not released"

            await session.execute(
                text("SELECT pg_advisory_unlock(:ns, :id)"),
                {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
            )
            await session.commit()

    @pytest.mark.asyncio
    async def test_the_lock_is_released_even_when_the_handler_raises(self):
        """A failing task must not poison its own lock forever."""

        task_name = "test.release_after_failure"

        async def handler():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await scheduler._run_once(
                PeriodicTask(name=task_name, interval_seconds=1, handler=handler)
            )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT pg_try_advisory_lock(:ns, :id)"),
                {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
            )

            assert result.scalar() is True, "lock leaked after a failure"

            await session.execute(
                text("SELECT pg_advisory_unlock(:ns, :id)"),
                {"ns": scheduler._LOCK_NAMESPACE, "id": _lock_id(task_name)},
            )
            await session.commit()


class TestLoopResilience:

    @pytest.mark.asyncio
    async def test_a_failing_task_does_not_kill_its_loop(self):
        """Silently stopping all future runs is worse than the failure."""

        attempts = []

        async def handler():
            attempts.append(1)
            raise RuntimeError("always fails")

        task = PeriodicTask(
            name="test.always_fails",
            interval_seconds=0.05,
            handler=handler,
            single_instance=False,
        )

        loop_task = asyncio.create_task(scheduler._loop(task))
        await asyncio.sleep(0.35)
        loop_task.cancel()

        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # Kept trying rather than dying on the first failure.
        assert len(attempts) >= 2


class TestConfiguration:

    def test_the_reaper_is_registered(self):
        from src.reports.tasks import register_tasks

        scheduler._TASKS.clear()
        register_tasks()

        names = {task.name for task in scheduler._TASKS}

        assert "report.reap_stale_executions" in names

        scheduler._TASKS.clear()

    def test_the_reaper_runs_more_often_than_a_lease_lasts(self):
        from src.core.config import settings

        # Otherwise a lapsed lease waits a whole extra lease period
        # before anything notices.
        assert (
            settings.REPORT_REAPER_INTERVAL_SECONDS
            < settings.REPORT_EXECUTION_LEASE_SECONDS
        )

    def test_start_is_a_no_op_when_disabled(self, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
        scheduler._running.clear()

        scheduler.start()

        assert scheduler._running == []
