"""Continuous monitoring: rules that watch a TM1 server, and their alerts.

The rules, in one place:

* **Monitoring only reads.** A check reads TM1's message log, element
  counts and security, and PA-Copilot's own records. It never writes to
  TM1, never runs a process, never drafts a change. What it finds becomes
  an alert for people to act on.
* **The assistant only suggests.** A rule it proposes starts `proposed` and
  is never checked until a person turns it on.
* **Each occurrence alerts once** (`dedup_key`): the same failed run, the
  same growth step, the same security difference is not raised twice.
* **A first check sets the baseline.** Nothing that happened before a rule
  existed alerts; growth and security are compared with what the first
  check saw.
* **Access follows the connection.** Making or seeing a rule or alert needs
  use of its TM1 connection; email goes only to people who still have it.
* **An unreachable server is said once**, after three failed checks in a
  row, not every fifteen minutes.

Kinds: process_failure, performance_regression, dimension_growth,
security_change, model_change, deployment. Server memory is not among them:
TM1 exposes it only through }StatsByServer with Performance Monitor on, and
that has not been verified against a real server.
"""

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from src.database.models.monitor import MonitorAlert, MonitorRule
from src.database.models.tm1_change import TM1Change
from src.database.models.tm1_connection import TM1Connection
from src.database.models.tm1_extraction import TM1Extraction
from src.database.models.tm1_health import TM1ProcessRun
from src.database.models.user import User
from src.email.registry import get_email_provider
from src.repositories.auth_repository import auth_repository
from src.services.audit_service import audit_service
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.health import performance
from src.tm1.resilience import call_with_resilience
from src.tm1.service import tm1_integration_service

KINDS = {
    "process_failure": "A process fails",
    "performance_regression": "A process runs much slower than usual",
    "dimension_growth": "A dimension grows unexpectedly",
    "security_change": "Users or group membership change",
    "model_change": "The model's objects change",
    "deployment": "A change is applied, fails or is rolled back",
}
MIN_INTERVAL_MINUTES = 15
ERRORS_BEFORE_ALERT = 3
# One scheduled pass stops starting new servers after this, inside the
# platform's 300 s function limit.
PASS_BUDGET_SECONDS = 200
MAX_ALERTS_PER_CHECK = 20
MAX_GROUPS = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate_params(kind: str, params: dict | None) -> dict:
    """The parameters a kind takes, checked and with defaults filled in."""

    if kind not in KINDS:
        raise ValidationException(f"kind must be one of: {', '.join(KINDS)}.")
    params = dict(params or {})

    def number(key, default, low, high):
        value = params.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationException(f"{key} must be a number.") from None
        if not low <= value <= high:
            raise ValidationException(f"{key} must be between {low:g} and {high:g}.")
        return value

    def text(key, required):
        value = str(params.get(key) or "").strip()
        if required and not value:
            raise ValidationException(f"{key} is required for this kind of rule.")
        if len(value) > 255:
            raise ValidationException(f"{key} is too long.")
        return value or None

    if kind == "process_failure":
        return {"process_name": text("process_name", False)}
    if kind == "performance_regression":
        return {
            "process_name": text("process_name", True),
            "factor": number("factor", 2, 1.1, 100),
            "window_days": int(number("window_days", 30, 1, 90)),
        }
    if kind == "dimension_growth":
        return {
            "dimension_name": text("dimension_name", True),
            "max_growth_percent": number("max_growth_percent", 10, 0, 10_000),
        }
    return {}


def describe(kind: str, params: dict) -> str:
    """The rule in a sentence, for names and emails."""

    if kind == "process_failure":
        return f"Alert when {params.get('process_name') or 'any process'} fails"
    if kind == "performance_regression":
        return (f"Alert when {params['process_name']} takes more than {params['factor']:g}x "
                f"its {params['window_days']}-day average")
    if kind == "dimension_growth":
        return f"Alert when {params['dimension_name']} grows more than {params['max_growth_percent']:g}%"
    return f"Alert when {KINDS[kind][0].lower()}{KINDS[kind][1:]}"


class _Check:
    """One server's evaluation: the connection, a client made on first use,
    and the message log collected at most once for all its rules."""

    def __init__(self, db: AsyncSession, connection: TM1Connection):
        self.db = db
        self.connection = connection
        self._client = None
        self._runs_collected = False

    async def client(self):
        if self._client is None:
            self._client = await tm1_connection_manager.get_client(self.connection)
        return self._client

    async def collect_runs(self):
        if not self._runs_collected:
            await performance.collect_runs(
                self.db, await self.client(), self.connection.id, self.connection.organization_id
            )
            self._runs_collected = True


async def _check_process_failure(check: _Check, rule: MonitorRule, since: datetime):
    await check.collect_runs()
    statement = select(TM1ProcessRun).where(
        TM1ProcessRun.connection_id == rule.connection_id,
        TM1ProcessRun.finished_at > since,
        TM1ProcessRun.outcome != "succeeded",
    )
    if rule.params.get("process_name"):
        statement = statement.where(TM1ProcessRun.process_name == rule.params["process_name"])
    runs = (await check.db.execute(statement.order_by(TM1ProcessRun.finished_at))).scalars()
    alerts = []
    for run in runs:
        outcome = run.outcome.replace("_", " ")
        alerts.append({
            "severity": "critical" if run.outcome == "aborted" else "warning",
            "title": f"{run.process_name} {outcome}",
            "detail": f"Finished {run.finished_at:%Y-%m-%d %H:%M} UTC with outcome '{outcome}'"
                      f" (from {'TM1 message log' if run.source == 'message_log' else 'a PA-Copilot run'}).",
            "evidence": {"process": run.process_name, "outcome": run.outcome,
                         "finished_at": run.finished_at.isoformat(), "elapsed_seconds": run.elapsed_seconds},
            "dedup_key": f"run:{run.process_name}:{run.finished_at.isoformat()}",
        })
    return alerts, None


async def _check_performance(check: _Check, rule: MonitorRule, since: datetime):
    await check.collect_runs()
    name, factor, days = rule.params["process_name"], rule.params["factor"], rule.params["window_days"]
    new_runs = (await check.db.execute(
        select(TM1ProcessRun).where(
            TM1ProcessRun.connection_id == rule.connection_id,
            TM1ProcessRun.process_name == name,
            TM1ProcessRun.finished_at > since,
            TM1ProcessRun.elapsed_seconds.is_not(None),
        ).order_by(TM1ProcessRun.finished_at)
    )).scalars().all()
    alerts = []
    for run in new_runs:
        earlier = (await check.db.execute(
            select(TM1ProcessRun.elapsed_seconds).where(
                TM1ProcessRun.connection_id == rule.connection_id,
                TM1ProcessRun.process_name == name,
                TM1ProcessRun.finished_at < run.finished_at,
                TM1ProcessRun.finished_at >= run.finished_at - timedelta(days=days),
                TM1ProcessRun.elapsed_seconds.is_not(None),
                TM1ProcessRun.outcome == "succeeded",
            )
        )).scalars().all()
        if len(earlier) < performance.MIN_PREVIOUS_RUNS:
            continue  # too little history to call anything unusual
        average = sum(earlier) / len(earlier)
        if average <= 0 or run.elapsed_seconds <= factor * average:
            continue
        alerts.append({
            "severity": "warning",
            "title": f"{name} took {run.elapsed_seconds / average:.1f}x its {days}-day average",
            "detail": (f"Run finished {run.finished_at:%Y-%m-%d %H:%M} UTC in {run.elapsed_seconds:.0f} s; "
                       f"the average of {len(earlier)} earlier successful runs is {average:.0f} s "
                       f"(threshold {factor:g}x)."),
            "evidence": {"elapsed_seconds": run.elapsed_seconds, "average_seconds": round(average, 1),
                         "earlier_runs": len(earlier), "factor": factor},
            "dedup_key": f"slow:{name}:{run.finished_at.isoformat()}",
        })
    return alerts, None


async def _check_dimension_growth(check: _Check, rule: MonitorRule, since: datetime):
    name, limit = rule.params["dimension_name"], rule.params["max_growth_percent"]
    client = await check.client()
    count = await call_with_resilience(
        rule.connection_id, client.elements.get_number_of_elements, name, name
    )
    baseline = (rule.state or {}).get("elements")
    if baseline is None:
        return [], {"elements": count, "since": _now().isoformat()}
    if baseline > 0 and count > baseline * (1 + limit / 100):
        growth = (count - baseline) / baseline * 100
        alert = {
            "severity": "warning",
            "title": f"{name} grew {growth:.0f}% ({baseline:,} → {count:,} elements)",
            "detail": f"More than the {limit:g}% allowed since {(rule.state or {}).get('since', 'the last baseline')}. "
                      "The new size is the baseline from now on.",
            "evidence": {"before": baseline, "after": count, "limit_percent": limit},
            "dedup_key": f"growth:{name}:{baseline}:{count}",
        }
        return [alert], {"elements": count, "since": _now().isoformat()}
    return [], rule.state


async def _check_security(check: _Check, rule: MonitorRule, since: datetime):
    client = await check.client()
    users = await call_with_resilience(rule.connection_id, client.security.get_all_users)
    snapshot: dict[str, list[str]] = {}
    for user in users or []:
        for group in sorted(getattr(user, "groups", []) or [])[:MAX_GROUPS]:
            snapshot.setdefault(str(group), []).append(str(user.name))
    snapshot = {group: sorted(members) for group, members in sorted(snapshot.items())}
    baseline = (rule.state or {}).get("groups")
    state = {"groups": snapshot}
    if baseline is None or baseline == snapshot:
        return [], state

    lines = []
    for group in sorted(set(baseline) | set(snapshot)):
        before, after = set(baseline.get(group, [])), set(snapshot.get(group, []))
        added, removed = sorted(after - before), sorted(before - after)
        if added:
            lines.append(f"{group}: added {', '.join(added)}")
        if removed:
            lines.append(f"{group}: removed {', '.join(removed)}")
    critical = any(line.startswith("ADMIN:") and "added" in line for line in lines)
    return [{
        "severity": "critical" if critical else "warning",
        "title": f"Security changed: {len(lines)} group membership change(s)",
        "detail": "\n".join(lines[:50]),
        "evidence": {"changes": lines[:200]},
        "dedup_key": "security:" + hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
    }], state


async def _check_model_change(check: _Check, rule: MonitorRule, since: datetime):
    extractions = (await check.db.execute(
        select(TM1Extraction).where(
            TM1Extraction.connection_id == rule.connection_id,
            TM1Extraction.status == "success",
            TM1Extraction.finished_at > since,
        ).order_by(TM1Extraction.finished_at)
    )).scalars()
    alerts = []
    for extraction in extractions:
        changes = extraction.changes or {}
        if changes.get("first"):
            continue  # the first map has nothing to differ from
        counts = {k: n for k, n in (changes.get("counts") or {}).items() if n}
        if not counts:
            continue
        summary = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items())
        examples = [
            f"{label}: {entry['type']} {entry['name']}"
            for key, label in (("objects_added", "added"), ("objects_removed", "removed"))
            for entry in (changes.get(key) or [])[:10]
        ]
        alerts.append({
            "severity": "info",
            "title": f"Model changed: {summary}",
            "detail": "\n".join(examples[:20]) or None,
            "evidence": {"extraction_id": str(extraction.id), "counts": counts},
            "dedup_key": f"extraction:{extraction.id}",
        })
    return alerts, None


async def _check_deployment(check: _Check, rule: MonitorRule, since: datetime):
    changes = (await check.db.execute(
        select(TM1Change).where(
            TM1Change.connection_id == rule.connection_id,
            or_(TM1Change.executed_at > since, TM1Change.rolled_back_at > since),
        )
    )).scalars()
    alerts = []
    for change in changes:
        what = f"{change.change_type.replace('_', ' ')} on {change.target_name}"
        if change.rolled_back_at and change.rolled_back_at > since:
            alerts.append({"severity": "warning", "title": f"Rolled back: {what}", "detail": None,
                           "evidence": {"change_id": str(change.id)},
                           "dedup_key": f"change:{change.id}:rolled_back"})
        if change.executed_at and change.executed_at > since and change.status == "unknown":
            alerts.append({
                "severity": "critical",
                "title": f"Outcome unknown: {what}",
                "detail": change.error_message,
                "evidence": {"change_id": str(change.id), "status": change.status},
                "dedup_key": f"change:{change.id}:unknown",
            })
        elif change.executed_at and change.executed_at > since:
            failed = change.status == "failed"
            alerts.append({
                "severity": "critical" if failed else "info",
                "title": f"{'Failed' if failed else 'Applied'}: {what}",
                "detail": change.error_message if failed else None,
                "evidence": {"change_id": str(change.id), "status": change.status},
                "dedup_key": f"change:{change.id}:{'failed' if failed else 'applied'}",
            })
    return alerts, None


EVALUATORS = {
    "process_failure": _check_process_failure,
    "performance_regression": _check_performance,
    "dimension_growth": _check_dimension_growth,
    "security_change": _check_security,
    "model_change": _check_model_change,
    "deployment": _check_deployment,
}


class MonitoringRulesService:

    # --- rules ---------------------------------------------------------

    async def _connection(self, db, connection_id, organization_id, user_id) -> TM1Connection:
        return await tm1_integration_service.get_connection(db, connection_id, organization_id, user_id=user_id)

    async def _may_edit(self, db, rule: MonitorRule, user_id) -> None:
        if rule.created_by == user_id:
            return
        if await auth_repository.user_has_permission(db, user_id, "tm1.connections.manage_all"):
            return
        raise PermissionDeniedException("Only the person who made this rule, or an admin, can change it.")

    async def _check_kind_permission(self, db, kind, user_id) -> None:
        # Watching who is in which group reads TM1 security, which is
        # narrower than tm1.read.
        if kind == "security_change" and not await auth_repository.user_has_permission(
            db, user_id, "tm1.security.read"
        ):
            raise PermissionDeniedException("Watching security changes needs the tm1.security.read permission.")

    async def get(self, db, rule_id, organization_id, user_id) -> MonitorRule:
        rule = await db.get(MonitorRule, rule_id)
        if rule is None or rule.organization_id != organization_id:
            raise NotFoundException("Rule not found.")
        try:
            await self._connection(db, rule.connection_id, organization_id, user_id)
        except NotFoundException:
            raise NotFoundException("Rule not found.") from None
        return rule

    async def create(
        self, db, *, organization_id, user_id, connection_id, kind, params=None, name=None,
        interval_minutes=MIN_INTERVAL_MINUTES, source="human", rationale=None,
    ) -> MonitorRule:
        await self._connection(db, connection_id, organization_id, user_id)
        params = validate_params(kind, params)
        await self._check_kind_permission(db, kind, user_id)
        rule = MonitorRule(
            organization_id=organization_id,
            connection_id=connection_id,
            name=(name or "").strip()[:255] or describe(kind, params),
            kind=kind,
            params=params,
            status="proposed" if source == "ai" else "active",
            source=source,
            rationale=(rationale or "").strip()[:2000] or None,
            interval_minutes=max(MIN_INTERVAL_MINUTES, int(interval_minutes or MIN_INTERVAL_MINUTES)),
            notify=[str(user_id)],
            created_by=user_id,
            consecutive_errors=0,
        )
        db.add(rule)
        await db.flush()
        await audit_service.log(
            db, organization_id=organization_id, user_id=user_id,
            action="monitor_proposed" if source == "ai" else "monitor_created",
            entity="MonitorRule", entity_id=rule.id,
            new_values={"kind": kind, "params": params, "connection_id": str(connection_id)},
        )
        return rule

    async def update(self, db, rule: MonitorRule, user_id, changes: dict) -> MonitorRule:
        await self._may_edit(db, rule, user_id)
        old = {}
        if "params" in changes and changes["params"] is not None:
            old["params"] = rule.params
            rule.params = validate_params(rule.kind, changes["params"])
            rule.state = None  # a new threshold starts a new baseline
        if changes.get("name"):
            old["name"] = rule.name
            rule.name = changes["name"].strip()[:255]
        if changes.get("interval_minutes"):
            old["interval_minutes"] = rule.interval_minutes
            rule.interval_minutes = max(MIN_INTERVAL_MINUTES, int(changes["interval_minutes"]))
        if changes.get("status"):
            if changes["status"] not in ("active", "paused"):
                raise ValidationException("status must be active or paused.")
            if changes["status"] == "active":
                await self._check_kind_permission(db, rule.kind, user_id)
                if rule.status == "proposed":
                    # Turned on by a person: from now on, like any rule.
                    rule.last_checked_at = None
            old["status"] = rule.status
            rule.status = changes["status"]
        if "notify" in changes and changes["notify"] is not None:
            old["notify"] = rule.notify
            rule.notify = [str(u) for u in changes["notify"]][:50]
        await db.flush()
        await db.refresh(rule)
        await audit_service.log(
            db, organization_id=rule.organization_id, user_id=user_id, action="monitor_updated",
            entity="MonitorRule", entity_id=rule.id, old_values=old,
            new_values={k: getattr(rule, k) for k in old},
        )
        return rule

    async def delete(self, db, rule: MonitorRule, user_id) -> None:
        await self._may_edit(db, rule, user_id)
        await audit_service.log(
            db, organization_id=rule.organization_id, user_id=user_id, action="monitor_deleted",
            entity="MonitorRule", entity_id=rule.id, old_values={"name": rule.name, "kind": rule.kind},
        )
        await db.delete(rule)
        await db.flush()

    async def usable_connection_ids(self, db, organization_id, user_id) -> list[uuid.UUID]:
        connections = await tm1_integration_service.list_connections(db, organization_id)
        return [c.id for c in connections if await tm1_integration_service.may_access(db, c, user_id=user_id)]

    async def list_rules(self, db, organization_id, user_id, connection_id=None) -> list[MonitorRule]:
        ids = await self.usable_connection_ids(db, organization_id, user_id)
        if connection_id:
            ids = [i for i in ids if i == connection_id]
        if not ids:
            return []
        result = await db.execute(
            select(MonitorRule).where(MonitorRule.connection_id.in_(ids)).order_by(MonitorRule.created_at.desc())
        )
        return list(result.scalars())

    # --- alerts --------------------------------------------------------

    async def list_alerts(self, db, organization_id, user_id, *, status=None, connection_id=None, limit=200):
        ids = await self.usable_connection_ids(db, organization_id, user_id)
        if connection_id:
            ids = [i for i in ids if i == connection_id]
        if not ids:
            return []
        statement = select(MonitorAlert).where(MonitorAlert.connection_id.in_(ids))
        if status:
            statement = statement.where(MonitorAlert.status == status)
        result = await db.execute(statement.order_by(MonitorAlert.fired_at.desc()).limit(limit))
        return list(result.scalars())

    async def set_alert_status(self, db, alert_id, organization_id, user_id, status: str) -> MonitorAlert:
        alert = await db.get(MonitorAlert, alert_id)
        if alert is None or alert.organization_id != organization_id:
            raise NotFoundException("Alert not found.")
        try:
            await self._connection(db, alert.connection_id, organization_id, user_id)
        except NotFoundException:
            raise NotFoundException("Alert not found.") from None
        if status not in ("acknowledged", "resolved"):
            raise ValidationException("status must be acknowledged or resolved.")
        old = alert.status
        alert.status = status
        if alert.acknowledged_by is None:
            alert.acknowledged_by, alert.acknowledged_at = user_id, _now()
        await db.flush()
        await db.refresh(alert)
        await audit_service.log(
            db, organization_id=organization_id, user_id=user_id, action=f"alert_{status}",
            entity="MonitorAlert", entity_id=alert.id, old_values={"status": old}, new_values={"status": status},
        )
        return alert

    # --- checking ------------------------------------------------------

    async def _raise(self, db, rule: MonitorRule, found: dict) -> MonitorAlert | None:
        result = await db.execute(
            insert(MonitorAlert)
            .values(
                id=uuid.uuid4(), organization_id=rule.organization_id, rule_id=rule.id,
                connection_id=rule.connection_id, severity=found["severity"], title=found["title"][:500],
                detail=found.get("detail"), evidence=found.get("evidence"), dedup_key=found["dedup_key"][:255],
                fired_at=_now(), status="open", emailed=False,
            )
            .on_conflict_do_nothing(constraint="uq_monitor_alerts_rule_key")
            .returning(MonitorAlert.id)
        )
        alert_id = result.scalar()
        return await db.get(MonitorAlert, alert_id) if alert_id else None

    async def check_rule(self, db, rule: MonitorRule, check: _Check) -> list[MonitorAlert]:
        """Evaluate one rule now. Returns the alerts it newly raised."""

        since = rule.last_checked_at or rule.created_at
        started = _now()
        raised: list[MonitorAlert] = []
        try:
            found, state = await EVALUATORS[rule.kind](check, rule, since)
        except Exception as exc:  # noqa: BLE001 - one rule's failure is recorded, not raised
            rule.consecutive_errors = (rule.consecutive_errors or 0) + 1
            rule.last_error = str(exc)[:1000] or exc.__class__.__name__
            if rule.consecutive_errors == ERRORS_BEFORE_ALERT:
                alert = await self._raise(db, rule, {
                    "severity": "warning",
                    "title": f"Cannot check '{rule.name}': the server did not answer {ERRORS_BEFORE_ALERT} times",
                    "detail": rule.last_error,
                    "evidence": {"errors": rule.consecutive_errors},
                    "dedup_key": f"unreachable:{started:%Y%m%d%H%M}",
                })
                if alert:
                    raised.append(alert)
            await db.flush()
            return raised

        for item in found[:MAX_ALERTS_PER_CHECK]:
            alert = await self._raise(db, rule, item)
            if alert:
                raised.append(alert)
        if state is not None:
            rule.state = state
        rule.last_checked_at = started
        rule.last_error = None
        rule.consecutive_errors = 0
        await db.flush()
        return raised

    async def check_now(self, db, rule: MonitorRule, user_id) -> list[MonitorAlert]:
        """A person asked: check this rule immediately."""

        if rule.status == "proposed":
            raise ValidationException("Turn the rule on first; a proposed rule is never checked.")
        connection = await self._connection(db, rule.connection_id, rule.organization_id, user_id)
        raised = await self.check_rule(db, rule, _Check(db, connection))
        await self.notify(db, raised)
        return raised

    async def notify(self, db, alerts: list[MonitorAlert]) -> int:
        """Email each new alert to its rule's subscribers who may still use
        the connection. Returns how many emails were handed to the provider."""

        if not alerts or not settings.SMTP_HOST:
            return 0
        sent = 0
        for alert in alerts:
            rule = await db.get(MonitorRule, alert.rule_id)
            connection = await db.get(TM1Connection, alert.connection_id)
            if rule is None or connection is None:
                continue
            ids = []
            for raw in rule.notify or []:
                try:
                    ids.append(uuid.UUID(str(raw)))
                except ValueError:
                    continue
            users = (await db.execute(select(User).where(User.id.in_(ids), User.is_active.is_(True)))).scalars()
            for user in users:
                if user.organization_id != alert.organization_id:
                    continue
                if not await tm1_integration_service.may_access(db, connection, user_id=user.id):
                    continue
                try:
                    await get_email_provider().send(
                        to=user.email,
                        subject=f"[PA-Copilot] {alert.severity.upper()}: {alert.title}"[:200],
                        body=(
                            f"{alert.title}\n\n"
                            f"Server: {connection.name} ({connection.environment.upper()})\n"
                            f"Rule: {rule.name}\n"
                            + (f"\n{alert.detail}\n" if alert.detail else "")
                            + f"\nSee it and acknowledge it: {settings.FRONTEND_URL}/alerts\n\n"
                            "Monitoring only reads your TM1 server; nothing was changed."
                        ),
                    )
                    sent += 1
                except Exception as exc:  # noqa: BLE001 - email failure must not lose the alert
                    logger.warning("Alert email to user {} failed: {}", user.id, exc)
            alert.emailed = sent > 0
        await db.flush()
        return sent


monitoring_rules_service = MonitoringRulesService()


async def run_due_monitors() -> dict:
    """One scheduled pass: every active rule whose interval has passed,
    grouped by server, each server in its own transaction, stalest first.
    Stops starting new servers when the time budget is spent; they are
    first in line next time."""

    from src.database.session import AsyncSessionLocal

    started = time.monotonic()
    now = _now()
    async with AsyncSessionLocal() as db:
        rules = (await db.execute(
            select(MonitorRule.id, MonitorRule.connection_id, MonitorRule.last_checked_at,
                   MonitorRule.interval_minutes)
            .where(MonitorRule.status == "active")
            .order_by(MonitorRule.last_checked_at.asc().nulls_first())
        )).all()

    by_connection: dict[uuid.UUID, list[uuid.UUID]] = {}
    for rule_id, connection_id, last, interval in rules:
        # A little early is fine: a pinger every 15 minutes must not skip a
        # 15-minute rule because it arrived a few seconds sooner.
        if last is None or last <= now - timedelta(minutes=interval) + timedelta(seconds=60):
            by_connection.setdefault(connection_id, []).append(rule_id)

    checked = raised = emailed = deferred = failed = 0
    for connection_id, rule_ids in by_connection.items():
        if time.monotonic() - started > PASS_BUDGET_SECONDS:
            deferred += len(rule_ids)
            continue
        try:
            async with AsyncSessionLocal() as db:
                connection = await db.get(TM1Connection, connection_id)
                if connection is None or not connection.is_active:
                    continue
                check = _Check(db, connection)
                new_alerts = []
                for rule_id in rule_ids:
                    rule = await db.get(MonitorRule, rule_id)
                    new_alerts += await monitoring_rules_service.check_rule(db, rule, check)
                    checked += 1
                await db.commit()
                raised += len(new_alerts)
                emailed += await monitoring_rules_service.notify(db, new_alerts)
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - one server must not stop the rest
            failed += 1
            logger.warning("Monitoring pass failed for connection {}: {}", connection_id, exc)

    return {"checked": checked, "alerts": raised, "emailed": emailed, "deferred": deferred, "failed": failed}
