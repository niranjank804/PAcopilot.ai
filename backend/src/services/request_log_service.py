"""Retention for the request log (models/request_log.py)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from src.core.config import settings
from src.database.models.request_log import RequestLog
from src.database.session import AsyncSessionLocal


async def purge_old_request_logs() -> int:
    """Delete request-log rows older than REQUEST_LOG_RETENTION_DAYS."""

    cutoff = datetime.now(UTC) - timedelta(days=max(1, settings.REQUEST_LOG_RETENTION_DAYS))
    async with AsyncSessionLocal() as session:
        result = await session.execute(delete(RequestLog).where(RequestLog.created_at < cutoff))
        await session.commit()
        return result.rowcount or 0
