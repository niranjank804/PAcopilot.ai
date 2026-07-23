import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.ai_usage import AIUsage


class AIUsageRepository:

    async def create(
        self,
        db: AsyncSession,
        usage: AIUsage,
    ) -> AIUsage:

        db.add(usage)

        await db.flush()

        await db.refresh(usage)

        return usage

    async def get_total_tokens_since(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        since: datetime,
    ) -> int:

        result = await db.execute(
            select(func.coalesce(func.sum(AIUsage.total_tokens), 0)).where(
                AIUsage.organization_id == organization_id,
                AIUsage.created_at >= since,
            )
        )

        return result.scalar_one()

    async def summarize(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        since: datetime,
    ) -> dict:

        result = await db.execute(
            select(
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.total_tokens), 0),
                func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
            ).where(
                AIUsage.organization_id == organization_id,
                AIUsage.created_at >= since,
            )
        )

        total_requests, total_tokens, total_cost_usd = result.one()

        return {
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
        }

    async def summarize_by_model(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        since: datetime,
    ) -> list[dict]:

        result = await db.execute(
            select(
                AIUsage.model,
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.total_tokens), 0),
                func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
            )
            .where(
                AIUsage.organization_id == organization_id,
                AIUsage.created_at >= since,
            )
            .group_by(AIUsage.model)
        )

        return [
            {
                "model": model,
                "requests": requests,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost_usd,
            }
            for model, requests, total_tokens, total_cost_usd in result.all()
        ]


ai_usage_repository = AIUsageRepository()
