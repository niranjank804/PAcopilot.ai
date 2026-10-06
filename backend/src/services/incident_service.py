"""Incident mode: "production allocation is wrong" — what changed, and what to do.

An investigation is deterministic and read-only. For one TM1 server and
the cube (or process) reported, it gathers, inside a time window:

1. the environment of the server;
2. the affected cube — given, or the cubes the reported process writes;
3. its neighbourhood from the dependency map: the processes that write it,
   and the cubes its rules read (and their writers);
4. PA-Copilot changes applied, failed or rolled back there;
5. process runs of the writers, from TM1's message log (collected now, best
   effort) and PA-Copilot's own runs: failures and slow runs;
6. model differences between metadata extractions that touch it;
7. the cube's rules, analysed;
8. open monitoring alerts on the server.

It ranks suspects — the things most likely to have changed the numbers —
and suggests a mitigation for each: roll back a change, diagnose and
re-run a process, review. **It applies nothing.** A rollback or a re-run is
a governed change a person approves; the investigation only points at it.

Kept as an IncidentInvestigation on the incident (a work item of kind
"incident"), so the timeline shows what was known when, and investigating
again after a fix shows what cleared.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.database.models.monitor import MonitorAlert
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_connection import TM1Connection
from src.database.models.tm1_extraction import TM1Extraction
from src.database.models.tm1_health import TM1ProcessRun
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.database.models.work_item import IncidentInvestigation, WorkItem
from src.services.audit_service import audit_service
from src.services.work_item_service import user_names, work_item_service
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.health import performance
from src.tm1.rules.analysis import analyze_rules
from src.tm1.service import tm1_integration_service
from src.tm1.services import cube_service

DEFAULT_WINDOW_HOURS = 48
MAX_WINDOW_HOURS = 24 * 30
SEVERITIES = ("low", "medium", "high", "critical")
MAX_SUSPECTS = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _neighbourhood(db, connection_id, cube: str | None, process: str | None) -> dict:
    """From the dependency map: the cubes involved, who writes them, and
    which cubes the affected cube's rules read."""

    objects = {
        (o.object_type, o.name): o
        for o in (await db.execute(
            select(TM1Object).where(TM1Object.connection_id == connection_id)
        )).scalars()
    }
    if not objects:
        return {"mapped": False, "cubes": [cube] if cube else [], "rule_sources": [], "writers": {},
                "reported_process_writes": []}

    by_id = {o.id: o for o in objects.values()}
    edges = (await db.execute(
        select(TM1Relationship).where(
            TM1Relationship.connection_id == connection_id,
            TM1Relationship.relationship_type.in_(("updates_cube", "references_cube")),
        )
    )).scalars().all()

    def edges_where(kind, *, to=None, frm=None):
        return [e for e in edges if e.relationship_type == kind
                and (to is None or e.to_object_id == to) and (frm is None or e.from_object_id == frm)]

    reported_writes = []
    if process and ("process", process) in objects:
        reported_writes = [by_id[e.to_object_id].name
                           for e in edges_where("updates_cube", frm=objects[("process", process)].id)
                           if e.to_object_id in by_id]

    cubes = [cube] if cube else reported_writes
    rule_sources = []
    for name in cubes:
        node = objects.get(("cube", name))
        if node:
            rule_sources += [by_id[e.to_object_id].name for e in edges_where("references_cube", frm=node.id)
                             if e.to_object_id in by_id and by_id[e.to_object_id].name not in cubes]

    writers: dict[str, list[str]] = {}
    for name in cubes + rule_sources:
        node = objects.get(("cube", name))
        if node:
            writers[name] = sorted({by_id[e.from_object_id].name for e in edges_where("updates_cube", to=node.id)
                                    if e.from_object_id in by_id})
    return {"mapped": True, "cubes": cubes, "rule_sources": sorted(set(rule_sources)), "writers": writers,
            "reported_process_writes": reported_writes}


class IncidentService:

    async def create_incident(
        self, db: AsyncSession, *, organization_id, user_id, reference, title, description,
        connection_id, severity, cube_name=None, process_name=None,
    ) -> WorkItem:
        if severity not in SEVERITIES:
            raise ValidationException(f"severity must be one of: {', '.join(SEVERITIES)}.")
        if not (cube_name or process_name):
            raise ValidationException("Name the cube that looks wrong, or the process that failed.")
        # The reporter must be able to use the server they report about.
        await tm1_integration_service.get_connection(db, connection_id, organization_id, user_id=user_id)
        item = await work_item_service.create(
            db, organization_id=organization_id, user_id=user_id,
            reference=reference, title=title, description=description,
        )
        item.kind, item.severity, item.connection_id = "incident", severity, connection_id
        item.cube_name = (cube_name or "").strip() or None
        item.process_name = (process_name or "").strip() or None
        await db.flush()
        await db.refresh(item)
        return item

    async def gather(
        self, db: AsyncSession, connection: TM1Connection, *, cube=None, process=None,
        window_hours=DEFAULT_WINDOW_HOURS,
    ) -> dict:
        """The evidence and the ranked suspects. Reads only."""

        window_hours = max(1, min(int(window_hours), MAX_WINDOW_HOURS))
        since = _now() - timedelta(hours=window_hours)
        notes: list[str] = []
        area = await _neighbourhood(db, connection.id, cube, process)
        if not area["mapped"]:
            notes.append("No dependency map for this server: writers and rule sources are unknown. "
                         "Run metadata extraction to include them.")
        cubes = set(area["cubes"]) | set(area["rule_sources"])
        writers = sorted({p for names in area["writers"].values() for p in names} | ({process} if process else set()))

        # Runs: collect what TM1 knows now, best effort.
        client = None
        try:
            client = await tm1_connection_manager.get_client(connection)
            await performance.collect_runs(db, client, connection.id, connection.organization_id)
        except Exception as exc:  # noqa: BLE001 - the rest of the evidence still stands
            notes.append(f"Could not read the server now ({type(exc).__name__}); runs and rules are "
                         "from what PA-Copilot recorded before.")
            client = None

        changes = (await db.execute(
            select(TM1Change).where(
                TM1Change.connection_id == connection.id,
                or_(TM1Change.executed_at >= since, TM1Change.rolled_back_at >= since),
            ).order_by(TM1Change.executed_at)
        )).scalars().all()

        runs = (await db.execute(
            select(TM1ProcessRun).where(
                TM1ProcessRun.connection_id == connection.id,
                TM1ProcessRun.finished_at >= since,
                TM1ProcessRun.process_name.in_(writers),
            ).order_by(TM1ProcessRun.finished_at)
        )).scalars().all() if writers else []

        extractions = (await db.execute(
            select(TM1Extraction).where(
                TM1Extraction.connection_id == connection.id,
                TM1Extraction.status == "success",
                TM1Extraction.finished_at >= since,
            )
        )).scalars().all()

        alerts = (await db.execute(
            select(MonitorAlert).where(
                MonitorAlert.connection_id == connection.id,
                MonitorAlert.status == "open",
                MonitorAlert.fired_at >= since,
            )
        )).scalars().all()

        rules_summary = None
        if client is not None and cube:
            try:
                rules = await cube_service.get_cube_rules(client, connection.id, cube)
                analysis = analyze_rules(rules)
                rules_summary = {
                    "has_rules": bool(rules),
                    "critical": analysis["summary"].get("critical", 0),
                    "warning": analysis["summary"].get("warning", 0),
                    "critical_findings": [
                        f["message"] for f in analysis["findings"] if f["severity"] == "critical"
                    ][:5],
                }
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Rules of {cube} could not be read ({type(exc).__name__}).")

        names = await user_names(db, {c.executed_by for c in changes} | {c.created_by for c in changes})
        suspects: list[dict] = []

        def suspect(score, kind, title, detail, at, mitigation, evidence):
            suspects.append({"score": score, "kind": kind, "title": title, "detail": detail,
                             "at": at.isoformat() if at else None, "mitigation": mitigation,
                             "evidence": evidence})

        for c in changes:
            on_cube = c.change_type in ("update_rules", "write_cells") and c.target_name in cubes
            on_writer = c.change_type.endswith("_process") and c.target_name in writers
            who = names.get(c.executed_by) or "someone"
            what = f"{c.change_type.replace('_', ' ')} on {c.target_name}"
            if c.status == "executed" and (on_cube or on_writer):
                if c.change_type == "run_process":
                    suspect(60, "run", f"{c.target_name} was run through PA-Copilot",
                            f"Run approved by {who}; a run writes data and cannot be rolled back.",
                            c.executed_at,
                            {"action": "review", "label": "Check what the run wrote; reverse it with another process if needed",
                             "change_id": str(c.id)},
                            {"change_id": str(c.id)})
                else:
                    score = 90 if c.change_type == "update_rules" else 85 if c.change_type == "write_cells" else 80
                    suspect(score, "change", f"Applied: {what}",
                            f"Applied by {who}"
                            + (f"; {c.target_name} is read by the rules of {', '.join(area['cubes'])}"
                               if c.target_name in area["rule_sources"] else ""),
                            c.executed_at,
                            {"action": "rollback", "label": f"Roll back this change ({what})",
                             "change_id": str(c.id)},
                            {"change_id": str(c.id)})
            elif c.status == "unknown" and (on_cube or on_writer):
                suspect(88, "change_unknown", f"Outcome unknown: {what}", c.error_message, c.executed_at,
                        {"action": "review", "label": "Check the object on the server; the change may have applied",
                         "change_id": str(c.id)},
                        {"change_id": str(c.id)})
            elif c.status == "failed" and (on_cube or on_writer):
                suspect(70, "change_failed", f"Failed: {what}", c.error_message, c.executed_at,
                        {"action": "review", "label": "Open the failed change", "change_id": str(c.id)},
                        {"change_id": str(c.id)})

        latest: dict[str, TM1ProcessRun] = {}
        for run in runs:
            latest[run.process_name] = run
        for name, run in latest.items():
            if run.outcome != "succeeded":
                suspect(75, "run_failed", f"{name} last ended '{run.outcome.replace('_', ' ')}'",
                        f"At {run.finished_at:%Y-%m-%d %H:%M} UTC; it writes "
                        f"{', '.join(c for c, ws in area['writers'].items() if name in ws) or 'the reported cube'}.",
                        run.finished_at,
                        {"action": "diagnose", "label": f"Diagnose {name}, fix it, then draft a re-run",
                         "process": name},
                        {"process": name, "outcome": run.outcome})
        for regression in (await performance.report(db, connection.id, connection.organization_id)).get(
            "regressions", []
        ):
            if regression["process"] in writers:
                suspect(40, "slow_run", f"{regression['process']} ran unusually long", regression["summary"],
                        None, {"action": "review", "label": "Check whether it finished its load",
                               "process": regression["process"]}, regression)

        watched = cubes | set(writers)
        for extraction in extractions:
            diff = extraction.changes or {}
            if diff.get("first"):
                continue
            touched = [
                f"{label} {entry['type']} {entry['name']}"
                for key, label in (("objects_added", "added"), ("objects_removed", "removed"))
                for entry in diff.get(key) or []
                if entry.get("name") in watched or entry.get("type") == "dimension"
            ]
            if touched:
                suspect(50, "model_change", "The model changed near it", "; ".join(touched[:8]),
                        extraction.finished_at,
                        {"action": "review", "label": "Review the model changes on the Metadata page"},
                        {"extraction_id": str(extraction.id)})

        for alert in alerts:
            suspect(45, "alert", f"Open alert: {alert.title}", alert.detail, alert.fired_at,
                    {"action": "review", "label": "Open it on the Alerts page", "alert_id": str(alert.id)},
                    {"alert_id": str(alert.id)})

        if rules_summary and rules_summary.get("critical_findings"):
            suspect(30, "rules", f"Rules of {cube} have critical findings",
                    "; ".join(rules_summary["critical_findings"]), None,
                    {"action": "review", "label": f"Ask the assistant to analyse the rules of {cube}"},
                    rules_summary)

        suspects.sort(key=lambda s: (-s["score"], s["at"] or ""), reverse=False)
        suspects = suspects[:MAX_SUSPECTS]
        summary = (
            f"{len(suspects)} suspect(s) in the last {window_hours} h on {connection.name} "
            f"({connection.environment.upper()}). Most likely: {suspects[0]['title']}."
            if suspects else
            f"Nothing changed, failed or differed near it in the last {window_hours} h on {connection.name} "
            f"({connection.environment.upper()}). Widen the window, or check the source data and inputs."
        )
        return {
            "summary": summary,
            "environment": connection.environment,
            "connection": connection.name,
            "window_hours": window_hours,
            "affected": {"cubes": area["cubes"], "rule_sources": area["rule_sources"],
                         "writers": area["writers"], "reported_process": process},
            "suspects": suspects,
            "evidence": {
                "changes": [{"id": str(c.id), "type": c.change_type, "target": c.target_name, "status": c.status,
                             "at": (c.executed_at or c.rolled_back_at).isoformat() if (c.executed_at or c.rolled_back_at) else None}
                            for c in changes][:50],
                "runs": [{"process": r.process_name, "outcome": r.outcome, "elapsed_seconds": r.elapsed_seconds,
                          "finished_at": r.finished_at.isoformat()} for r in runs][-50:],
                "model_extractions": len(extractions),
                "open_alerts": len(alerts),
                "rules": rules_summary,
            },
            "notes": notes,
            "applied_nothing": "This investigation only read. Every mitigation is a change a person approves.",
        }

    async def investigate(self, db: AsyncSession, item: WorkItem, user_id, *, window_hours=None) -> IncidentInvestigation:
        if item.kind != "incident" or item.connection_id is None:
            raise ValidationException("Only an incident on a TM1 server can be investigated.")
        connection = await tm1_integration_service.get_connection(
            db, item.connection_id, item.organization_id, user_id=user_id
        )
        findings = await self.gather(
            db, connection, cube=item.cube_name, process=item.process_name,
            window_hours=window_hours or DEFAULT_WINDOW_HOURS,
        )
        investigation = IncidentInvestigation(
            organization_id=item.organization_id, work_item_id=item.id, connection_id=connection.id,
            run_by=user_id, window_hours=findings["window_hours"], summary=findings["summary"][:2000],
            findings=findings,
            # The moment of the look, not of the transaction: two looks in one
            # transaction must still order.
            created_at=_now(),
        )
        db.add(investigation)
        await db.flush()
        await audit_service.log(
            db, organization_id=item.organization_id, user_id=user_id, action="incident_investigated",
            entity="WorkItem", entity_id=item.id,
            new_values={"suspects": len(findings["suspects"]), "window_hours": findings["window_hours"]},
        )
        logger.info("Incident {} investigated: {} suspects", item.reference, len(findings["suspects"]))
        return investigation

    async def investigations(self, db: AsyncSession, item: WorkItem, user_id) -> list[IncidentInvestigation] | None:
        """Newest first; None when this person may not use the server (the
        findings name its changes and processes)."""

        if item.connection_id is None:
            return []
        try:
            await tm1_integration_service.get_connection(db, item.connection_id, item.organization_id, user_id=user_id)
        except NotFoundException:
            return None
        result = await db.execute(
            select(IncidentInvestigation)
            .where(IncidentInvestigation.work_item_id == item.id)
            .order_by(IncidentInvestigation.created_at.desc())
        )
        return list(result.scalars())


incident_service = IncidentService()

