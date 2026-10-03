import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.ai_tool_execution_repository import ai_tool_execution_repository
from src.repositories.ai_usage_repository import ai_usage_repository
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

        # Only connections the caller may see: a member's private
        # connection is not listed to the rest of the organization.
        from src.tm1.service import tm1_integration_service

        connections = await tm1_integration_service.list_connections(
            db, organization_id, purpose="manage"
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


async def ai_cost_report(db: AsyncSession, organization_id: uuid.UUID, days: int) -> dict:
    """Where AI spend goes, and what routing and caching saved.

    Everything is computed from the usage ledger (ai_usage), one row per
    answered turn, priced with src/ai/pricing.py. Two numbers are estimates
    and say so: the AUTO saving assumes the BEST model would have used the
    same tokens; neither accounts for Anthropic invoice adjustments.
    """

    import statistics

    from sqlalchemy import func, select

    from src.ai.pricing import cost_without_cache, estimate_cost
    from src.ai.routing import TIER_MODELS
    from src.ai.schemas import Usage
    from src.database.models.ai_tool_execution import AIToolExecution
    from src.database.models.ai_usage import AIUsage
    from src.database.models.user import User

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(AIUsage).where(
                AIUsage.organization_id == organization_id,
                AIUsage.created_at >= since,
            )
        )
    ).scalars().all()
    tool_calls = (
        await db.execute(
            select(func.count()).select_from(AIToolExecution).where(
                AIToolExecution.organization_id == organization_id,
                AIToolExecution.created_at >= since,
            )
        )
    ).scalar_one()

    def group(key) -> list[dict]:
        totals: dict[str, dict] = {}
        for row in rows:
            name = key(row) or "unknown"
            entry = totals.setdefault(name, {"name": name, "requests": 0, "cost_usd": 0.0})
            entry["requests"] += 1
            entry["cost_usd"] += float(row.estimated_cost_usd)
        out = sorted(totals.values(), key=lambda e: -e["cost_usd"])
        for entry in out:
            entry["cost_usd"] = round(entry["cost_usd"], 4)
            entry["cost_per_request_usd"] = round(entry["cost_usd"] / entry["requests"], 4)
        return out

    users = {
        u.id: f"{u.first_name} {u.last_name}".strip() or u.username
        for u in (
            await db.execute(select(User).where(User.id.in_({r.user_id for r in rows})))
        ).scalars()
    } if rows else {}

    cache_saving = 0.0
    auto_saving = 0.0
    auto_rows = 0
    for row in rows:
        usage = Usage(
            input_tokens=row.prompt_tokens,
            output_tokens=row.completion_tokens,
            cache_creation_input_tokens=row.cache_creation_tokens,
            cache_read_input_tokens=row.cache_read_tokens,
        )
        cache_saving += float(cost_without_cache(row.model, usage) - estimate_cost(row.model, usage))
        if (row.route_reason or "").startswith("AUTO") and row.tier != "best":
            auto_rows += 1
            auto_saving += float(estimate_cost(TIER_MODELS["best"], usage) - estimate_cost(row.model, usage))

    routed = [r for r in rows if r.tier is not None]
    latencies = [r.latency_ms for r in rows]
    total_cost = sum(float(r.estimated_cost_usd) for r in rows)

    return {
        "days": days,
        "requests": len(rows),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_request_usd": round(total_cost / len(rows), 4) if rows else 0.0,
        "tool_calls": tool_calls,
        "avg_latency_ms": round(statistics.mean(latencies)) if latencies else 0,
        "p95_latency_ms": (
            round(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20
            else max(latencies, default=0)
        ),
        "fallback_rate": round(sum(1 for r in routed if r.fell_back) / len(routed), 4) if routed else 0.0,
        "by_agent": group(lambda r: r.agent or ("plain chat" if r.tier else None)),
        "by_tier": group(lambda r: r.tier),
        "by_model": group(lambda r: r.model),
        "by_user": group(lambda r: users.get(r.user_id)),
        "cache_savings_usd": round(cache_saving, 4),
        "auto_routing": {
            "requests": auto_rows,
            "estimated_savings_usd": round(auto_saving, 4),
            "assumption": (
                "Estimated as the same tokens priced at the BEST model. A larger "
                "model may use more or fewer tokens, so this is an estimate, "
                "not a measurement."
            ),
        },
        "notes": [
            "Costs are estimates from published per-token rates (src/ai/pricing.py), "
            "not Anthropic's invoice.",
            "Requests made before routing existed show as tier 'unknown'.",
        ],
    }
