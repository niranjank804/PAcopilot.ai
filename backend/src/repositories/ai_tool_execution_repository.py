import json
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
        tool_names: frozenset[str],
    ) -> bool:
        """Whether one of the `tool_names` (the draft-producing tools), called
        by this user in this conversation, produced the draft `change_id`.

        A draft tool's result is JSON whose first field is draft_change_id,
        and the summary is that JSON re-serialised in the same order, so the
        stored text begins `{"draft_change_id": "<id>"` — a position only
        the tool writes to. The match is on that prefix, never on the id
        appearing anywhere in the text, where echoed input (a rule, an
        error message) could place it."""

        prefix = json.dumps({"draft_change_id": str(change_id)})[:-1]
        result = await db.execute(
            select(AIToolExecution.id)
            .where(
                AIToolExecution.conversation_id == conversation_id,
                AIToolExecution.user_id == user_id,
                AIToolExecution.tool_name.in_(tool_names),
                AIToolExecution.status == "success",
                AIToolExecution.result_summary.startswith(prefix, autoescape=True),
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
