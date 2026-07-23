import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from src.repositories.ai_usage_repository import ai_usage_repository
from src.repositories.tm1_connection_repository import tm1_connection_repository
from src.tm1.resilience import CircuitState, peek_circuit_breaker


class MonitoringService:

    async def get_usage_summary(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        days: int,
    ) -> dict:

        since = datetime.now(timezone.utc) - timedelta(days=days)

        summary = await ai_usage_repository.summarize(db, organization_id, since)
        by_model = await ai_usage_repository.summarize_by_model(
            db, organization_id, since
        )

        return {**summary, "by_model": by_model}

    async def get_tool_summary(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        days: int,
    ) -> list[dict]:

        since = datetime.now(timezone.utc) - timedelta(days=days)

        return await ai_tool_execution_repository.summarize_by_tool(
            db, organization_id, since
        )

    async def get_tm1_status(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[dict]:

        connections = await tm1_connection_repository.list_by_organization(
            db, organization_id
        )

        statuses = []

        for connection in connections:
            breaker = peek_circuit_breaker(connection.id)

            statuses.append(
                {
                    "connection_id": connection.id,
                    "name": connection.name,
                    "state": (
                        breaker.state.value if breaker else CircuitState.CLOSED.value
                    ),
                    "failure_count": breaker.failure_count if breaker else 0,
                }
            )

        return statuses


monitoring_service = MonitoringService()
