"""Periodic report-automation work.

Before this existed, `reap_stale_executions()` ran only when a worker
happened to poll for a job. That left a real hole: an organization whose
worker crashed had nothing polling, so the very executions the reaper
exists to reclaim were the ones it never saw. An execution could sit
RUNNING forever, holding a lease nobody would ever release, and its
retry would never be created.

Running it on a timer closes that. The opportunistic call on claim is
kept as well — it costs almost nothing and reclaims work fractionally
sooner when a worker *is* active.
"""

from src.core.config import settings
from src.core.logging import app_logger
from src.core.scheduler import PeriodicTask, register
from src.database.session import AsyncSessionLocal
from src.reports.execution_service import execution_service


async def reap_stale_executions() -> None:
    """Reclaim executions whose worker stopped heartbeating.

    Runs across every organization: `organization_id=None` is the
    all-tenant sweep. That is safe here specifically because this is a
    system task with no user context — it is not reachable from a
    request, and the tenancy filter only applies to sessions that have
    been stamped with an organization by `get_current_user`.
    """

    async with AsyncSessionLocal() as session:
        try:
            reaped = await execution_service.reap_stale_executions(
                session, organization_id=None
            )

            # Commit explicitly: this session is created here rather than
            # by the request-scoped get_db dependency, so nothing else
            # will commit it.
            await session.commit()

            if reaped:
                app_logger.info(
                    f"report reaper reclaimed {reaped} stale execution(s)"
                )
        except Exception:
            await session.rollback()

            raise


def register_tasks() -> None:
    register(
        PeriodicTask(
            name="report.reap_stale_executions",
            interval_seconds=settings.REPORT_REAPER_INTERVAL_SECONDS,
            handler=reap_stale_executions,
        )
    )
