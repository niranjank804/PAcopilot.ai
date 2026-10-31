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

    async def drafted_in_conversation(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        change_id: uuid.UUID,
    ) -> bool:
        """Whether a propose_* call by this user, in this conversation,
        produced the draft `change_id`. A propose result names the draft
        first, so the 500-character summary always still holds the id."""

        result = await db.execute(
            select(AIToolExecution.id)
            .where(
                AIToolExecution.conversation_id == conversation_id,
                AIToolExecution.user_id == user_id,
                AIToolExecution.tool_name.startswith("propose_", autoescape=True),
                AIToolExecution.status == "success",
                AIToolExecution.result_summary.contains(str(change_id)),
            )
            .limit(1)
        )

        return result.scalar_one_or_none() is not None

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
                # Expected negatives ("no such process") are counted apart
                # from failures so error_count stays a health signal.
                func.count(AIToolExecution.id).filter(
                    AIToolExecution.status == "not_found"
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
                "not_found_count": not_found_count,
                "avg_duration_ms": float(avg_duration_ms),
            }
            for (
                tool_name,
                total_calls,
                success_count,
                error_count,
                not_found_count,
                avg_duration_ms,
            ) in result.all()
        ]


ai_tool_execution_repository = AIToolExecutionRepository()
