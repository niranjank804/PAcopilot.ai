"""Model health score and performance history, for the agents.

run_model_health_check audits rules and processes on demand. These two add
what persists between conversations: the scored scan and its trend, and the
run-time history that turns "it feels slow" into "it normally takes 42 s
and took 7 min 18 s this morning".
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.tm1._common import CONNECTION_ID_SCHEMA, TM1Tool, connection_id_of, evidence
from src.tm1.health import performance
from src.tm1.health import score as health_score
from src.tm1.service import tm1_integration_service


class GetModelHealthTool(TM1Tool):

    name = "get_model_health"
    description = (
        "The model's health score (0-100, graded A-F) with every point taken "
        "off and the objects that cost it: critical rule findings, process "
        "errors, rule warnings, performance regressions, recently failed "
        "processes, other process findings and unused objects. Returns the "
        "latest saved scan and the trend of recent scores; rescan=true scans "
        "now (slower: reads every rule and process). Use for 'how healthy is "
        "this model', 'what should we fix first', or 'is it getting worse'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "connection_id": CONNECTION_ID_SCHEMA,
            "rescan": {"type": "boolean", "description": "Scan now instead of reading the latest scan."},
        },
        "required": ["connection_id"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        connection = await tm1_integration_service.get_connection(
            db, connection_id_of(kwargs), organization_id
        )

        if kwargs.get("rescan"):
            await health_score.run_health_scan(db, connection.id, organization_id, trigger="manual")

        scans = await health_score.recent_scans(db, connection.id, organization_id)
        latest = scans[0] if scans else None

        return json.dumps(
            {
                "latest": (
                    {
                        "scanned_at": latest.scanned_at,
                        "score": latest.score,
                        "grade": latest.grade,
                        "deductions": [d for d in latest.deductions if d["count"]],
                        "notes": latest.totals.get("notes", []),
                        "worst_rules": (latest.findings or {}).get("rules", [])[:5],
                        "worst_processes": (latest.findings or {}).get("processes", [])[:5],
                    }
                    if latest
                    else None
                ),
                "trend": [{"scanned_at": s.scanned_at, "score": s.score} for s in scans],
                "scoring": (
                    "100 minus fixed points per finding, capped per category: "
                    "see each deduction's points_each and cap."
                ),
                "evidence": evidence(
                    verified=["Rule text and process source read from TM1 at scan time"] if latest else [],
                    unknown=[] if latest else ["No scan yet: call again with rescan=true"],
                ),
            },
            default=str,
        )


class GetPerformanceReportTool(TM1Tool):

    name = "get_performance_report"
    description = (
        "How long processes take, from the run history PA-Copilot collects "
        "from TM1's message log: regressions (a latest run far slower than "
        "its usual time, with the usual time, the latest time and the % "
        "increase), the slowest processes by median, and processes that "
        "failed in the last 7 days. Collects the newest runs first. Use for "
        "'why is X slow', 'what got slower', 'which loads fail'."
    )
    input_schema = {
        "type": "object",
        "properties": {"connection_id": CONNECTION_ID_SCHEMA},
        "required": ["connection_id"],
    }

    async def execute(self, db: AsyncSession, *, organization_id, user_id, **kwargs) -> str:
        await self._authorize(db, user_id)

        connection, client = await tm1_integration_service.connect(
            db, connection_id_of(kwargs), organization_id
        )
        unknown = []
        try:
            await performance.collect_runs(db, client, connection.id, organization_id)
        except Exception as exc:  # noqa: BLE001 - the stored history still answers
            unknown.append(f"The newest runs could not be read from TM1 ({type(exc).__name__}); history so far only")

        result = await performance.report(db, connection.id, organization_id)
        result["evidence"] = evidence(
            verified=["Run times as TM1 wrote them in its message log, or recorded by PA-Copilot"],
            inferred=["Whether a regression matters, and why it happened"] if result["regressions"] else [],
            unknown=unknown + result["not_covered"],
        )
        return json.dumps(result, default=str)
