"""The TM1 Engineering Command Center: everything that needs attention, at once.

One read, from what PA-Copilot has already recorded — no TM1 calls, so it
answers in milliseconds and never waits on a slow server. Each section is
limited to the TM1 connections this person may use; AI usage and cost are
the organization's, as on the Monitoring page.

Sections: model health and the risks behind the scores, active incidents,
failed processes, performance regressions, open alerts, changes waiting
for approval, recent deployments, recent model changes, AI usage and cost.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies.permissions import require_permission
from src.database.models.ai_usage import AIUsage
from src.database.models.monitor import MonitorAlert
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_extraction import TM1Extraction
from src.database.models.tm1_health import TM1HealthScan
from src.database.models.work_item import WorkItem
from src.database.session import get_db
from src.schemas.auth import UserResponse
from src.schemas.response import ApiResponse
from src.services.work_item_service import user_names
from src.tm1.health import performance
from src.tm1.service import tm1_integration_service

router = APIRouter(prefix="/command-center", tags=["Command center"])

RECENT_DAYS = 14
AI_DAYS = 30
MAX_ROWS = 10


def _server(connection) -> dict:
    return {"connection_id": str(connection.id), "connection_name": connection.name,
            "environment": connection.environment}


@router.get("", response_model=ApiResponse[dict])
async def command_center(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_permission("monitoring.view")),
):
    organization_id, user_id = current_user.organization_id, current_user.id
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=RECENT_DAYS)

    connections = {
        c.id: c for c in await tm1_integration_service.list_connections(db, organization_id)
        if await tm1_integration_service.may_access(db, c, user_id=user_id)
    }
    ids = list(connections)

    # Model health: the latest scan of each server, and the risks behind it.
    health, risks = [], {}
    if ids:
        # Only each server's latest scan: scans accumulate daily, and reading
        # every one of them to keep the first grew slower every day.
        scans = (await db.execute(
            select(TM1HealthScan).where(TM1HealthScan.connection_id.in_(ids))
            .distinct(TM1HealthScan.connection_id)
            .order_by(TM1HealthScan.connection_id, TM1HealthScan.scanned_at.desc())
        )).scalars()
        seen = set()
        for scan in scans:
            if scan.connection_id in seen:
                continue
            seen.add(scan.connection_id)
            health.append({**_server(connections[scan.connection_id]), "score": scan.score, "grade": scan.grade,
                           "scanned_at": scan.scanned_at})
            for d in scan.deductions or []:
                if d.get("points"):
                    entry = risks.setdefault(d["category"], {"category": d["category"], "label": d["label"],
                                                             "count": 0, "points": 0.0, "servers": []})
                    entry["count"] += d.get("count", 0)
                    entry["points"] += d["points"]
                    entry["servers"].append(connections[scan.connection_id].name)
    health.sort(key=lambda h: h["score"])

    # Performance: regressions and failures from the recorded run history.
    regressions, failures = [], []
    for connection in connections.values():
        report = await performance.report(db, connection.id, organization_id)
        regressions += [{**_server(connection), **r} for r in report["regressions"]]
        failures += [{**_server(connection), **f} for f in report["failures_7_days"]]

    alerts = list((await db.execute(
        select(MonitorAlert).where(MonitorAlert.connection_id.in_(ids), MonitorAlert.status == "open")
        .order_by(MonitorAlert.fired_at.desc()).limit(50)
    )).scalars()) if ids else []

    incidents = list((await db.execute(
        select(WorkItem).where(
            WorkItem.organization_id == organization_id, WorkItem.kind == "incident",
            WorkItem.status.in_(("open", "in_progress")),
        ).order_by(WorkItem.updated_at.desc()).limit(MAX_ROWS)
    )).scalars())

    changes = list((await db.execute(
        select(TM1Change).where(
            TM1Change.connection_id.in_(ids),
            or_(TM1Change.status == "draft", TM1Change.executed_at >= recent, TM1Change.rolled_back_at >= recent),
        ).order_by(TM1Change.created_at.desc()).limit(100)
    )).scalars()) if ids else []
    names = await user_names(db, {c.created_by for c in changes} | {c.executed_by for c in changes})

    def change_row(c):
        return {**_server(connections[c.connection_id]), "id": str(c.id), "change_type": c.change_type,
                "target_name": c.target_name, "status": c.status, "created_at": c.created_at,
                "executed_at": c.executed_at, "rolled_back_at": c.rolled_back_at,
                "by": names.get(c.executed_by or c.created_by)}

    pending = [change_row(c) for c in changes if c.status == "draft" and not c.validation_errors][:MAX_ROWS]
    deployments = [change_row(c) for c in sorted(
        (c for c in changes if c.executed_at and c.executed_at >= recent or (c.rolled_back_at and c.rolled_back_at >= recent)),
        key=lambda c: c.rolled_back_at or c.executed_at, reverse=True)][:MAX_ROWS]

    model_changes = []
    if ids:
        for extraction in (await db.execute(
            select(TM1Extraction).where(
                TM1Extraction.connection_id.in_(ids), TM1Extraction.status == "success",
                TM1Extraction.finished_at >= recent,
            ).order_by(TM1Extraction.finished_at.desc())
        )).scalars():
            diff = extraction.changes or {}
            counts = {k: n for k, n in (diff.get("counts") or {}).items() if n}
            if counts and not diff.get("first"):
                model_changes.append({**_server(connections[extraction.connection_id]),
                                      "at": extraction.finished_at, "counts": counts})

    since_ai = now - timedelta(days=AI_DAYS)
    ai = (await db.execute(
        select(func.count(AIUsage.id), func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0),
               func.coalesce(func.avg(AIUsage.latency_ms), 0))
        .where(AIUsage.organization_id == organization_id, AIUsage.created_at >= since_ai)
    )).one()

    return ApiResponse(success=True, data={
        "generated_at": now,
        "servers": len(connections),
        "health": health,
        "risks": sorted(risks.values(), key=lambda r: -r["points"])[:8],
        "incidents": [{"id": str(i.id), "reference": i.reference, "title": i.title, "severity": i.severity,
                       "status": i.status, "updated_at": i.updated_at} for i in incidents],
        "failed_processes": sorted(failures, key=lambda f: f["last_failed_at"], reverse=True)[:MAX_ROWS],
        "regressions": regressions[:MAX_ROWS],
        "alerts": {"open": len(alerts), "critical": sum(a.severity == "critical" for a in alerts),
                   "latest": [{"id": str(a.id), "title": a.title, "severity": a.severity, "fired_at": a.fired_at,
                               **_server(connections[a.connection_id])} for a in alerts[:5]]},
        "pending_approvals": pending,
        "deployments": deployments,
        "model_changes": model_changes[:MAX_ROWS],
        "ai": {"days": AI_DAYS, "requests": int(ai[0]), "cost_usd": round(float(ai[1]), 2),
               "avg_latency_ms": int(ai[2])},
    })
