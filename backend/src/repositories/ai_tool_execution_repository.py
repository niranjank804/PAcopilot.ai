import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.ai_tool_execution import AIToolExecution


class AIToolExecutionRepository:

    async def create(
        self,
        db: AsyncSession,
        execution: AIToolExecution,
    ) -> AIToolExecution:

        db.add(execution)

        await db.flush()

        await db.refresh(execution)

        return execution

    async def list_by_conversation(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> list[AIToolExecution]:

        result = await db.execute(
            select(AIToolExecution)
            .where(AIToolExecution.conversation_id == conversation_id)
            .order_by(AIToolExecution.created_at)
        )

        return list(result.scalars().all())

    async def summarize_by_tool(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        since: datetime,
    ) -> list[dict]:

        result = await db.execute(
            select(
                AIToolExecution.tool_name,
                func.count(AIToolExecution.id),
                func.count(AIToolExecution.id).filter(
                    AIToolExecution.status == "success"
                ),
                func.count(AIToolExecution.id).filter(
                    AIToolExecution.status == "error"
                ),
                func.coalesce(func.avg(AIToolExecution.duration_ms), 0),
            )
            .where(
                AIToolExecution.organization_id == organization_id,
                AIToolExecution.created_at >= since,
            )
            .group_by(AIToolExecution.tool_name)
        )

        return [
            {
                "tool_name": tool_name,
                "total_calls": total_calls,
                "success_count": success_count,
                "error_count": error_count,
                "avg_duration_ms": float(avg_duration_ms),
            }
            for (
                tool_name,
                total_calls,
                success_count,
                error_count,
                avg_duration_ms,
            ) in result.all()
        ]


ai_tool_execution_repository = AIToolExecutionRepository()
