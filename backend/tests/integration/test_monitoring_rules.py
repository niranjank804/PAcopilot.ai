"""Continuous monitoring: rules that only read, alerts raised once.

What must hold: a first check sets a baseline and never alerts on the past;
each occurrence alerts once; the assistant's rules wait for a person to
turn them on; access follows the TM1 connection; an unreachable server is
said once, not every check; email goes to subscribers who may still use
the connection.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.ai.tools.monitors import ProposeMonitorTool
from src.core.config import settings
from src.database.models.tm1_health import TM1ProcessRun
from src.services import monitoring_rules_service as monitoring
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _draft, _execute, _user_with


@pytest.fixture
async def team(db_session, tm1_credentials_key, fake_tm1_client, client):
    fake_tm1_client.server.get_message_log_entries.return_value = []
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    a = await _user_with(db_session, org_id, "monitoring.view")
    b = await _user_with(db_session, org_id, "monitoring.view")
    await db_session.commit()
    headers = auth_headers(admin)
    connection = await _connection(client, headers, "dev")  # shared with the organization
    return {"org_id": org_id, "admin": headers, "admin_id": admin.id, "a": auth_headers(a), "a_id": a.id,
            "b": auth_headers(b), "b_id": b.id, "connection": connection, "tm1": fake_tm1_client}


async def _rule(client, headers, connection, kind, **params):
    resp = await client.post(
        "/monitoring/rules", json={"connection_id": connection, "kind": kind, "params": params}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _check(client, headers, rule_id):
    resp = await client.post(f"/monitoring/rules/{rule_id}/check", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _run(db_session, team, process, *, ago=None, ahead=None, seconds=100.0, outcome="succeeded"):
    now = datetime.now(timezone.utc)
    finished = now - ago if ago else now + (ahead or timedelta(seconds=5))
    db_session.add(TM1ProcessRun(
        id=uuid.uuid4(), connection_id=uuid.UUID(team["connection"]), organization_id=team["org_id"],
        process_name=process, finished_at=finished, elapsed_seconds=seconds, outcome=outcome, source="message_log",
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_failure_before_the_rule_never_alerts_and_a_new_one_alerts_once(client, db_session, team):
    await _run(db_session, team, "Load Sales", ago=timedelta(hours=2), outcome="aborted")
    rule = await _rule(client, team["a"], team["connection"], "process_failure", process_name="Load Sales")

    assert await _check(client, team["a"], rule["id"]) == []

    await _run(db_session, team, "Load Sales", outcome="aborted")
    await _run(db_session, team, "Load Rates", outcome="aborted")  # another process: not this rule
    raised = await _check(client, team["a"], rule["id"])
    assert [a["title"] for a in raised] == ["Load Sales aborted"]
    assert raised[0]["severity"] == "critical"

    assert await _check(client, team["a"], rule["id"]) == []  # once per occurrence

    # B uses the same shared server: sees it, and can acknowledge it.
    open_for_b = (await client.get("/monitoring/alerts?status=open", headers=team["b"])).json()["data"]
    assert [a["id"] for a in open_for_b] == [raised[0]["id"]]
    acked = await client.post(f"/monitoring/alerts/{raised[0]['id']}/acknowledge", headers=team["b"])
    assert acked.status_code == 200 and acked.json()["data"]["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_twice_the_thirty_day_average_alerts(client, db_session, team):
    for days in (3, 2, 1):
        await _run(db_session, team, "Workforce Planning", ago=timedelta(days=days), seconds=100)
    rule = await _rule(client, team["a"], team["connection"], "performance_regression",
                       process_name="Workforce Planning", factor=2, window_days=30)
    assert rule["name"] == "Alert when Workforce Planning takes more than 2x its 30-day average"

    await _run(db_session, team, "Workforce Planning", ahead=timedelta(seconds=5), seconds=150)
    assert await _check(client, team["a"], rule["id"]) == []  # 1.5x: within the threshold

    await _run(db_session, team, "Workforce Planning", ahead=timedelta(seconds=30), seconds=500)
    raised = await _check(client, team["a"], rule["id"])
    assert len(raised) == 1 and "x its 30-day average" in raised[0]["title"]
    assert raised[0]["evidence"]["earlier_runs"] == 4


@pytest.mark.asyncio
async def test_dimension_growth_compares_with_the_first_check(client, db_session, team):
    counts = iter([100, 105, 120, 121])
    team["tm1"].elements.get_number_of_elements.side_effect = lambda *_: next(counts)
    rule = await _rule(client, team["a"], team["connection"], "dimension_growth",
                       dimension_name="Employee", max_growth_percent=10)

    assert await _check(client, team["a"], rule["id"]) == []   # baseline 100
    assert await _check(client, team["a"], rule["id"]) == []   # 105: within 10%
    raised = await _check(client, team["a"], rule["id"])       # 120: 20% over 100
    assert raised[0]["title"] == "Employee grew 20% (100 → 120 elements)"
    assert await _check(client, team["a"], rule["id"]) == []   # 121 against the new baseline 120


@pytest.mark.asyncio
async def test_security_changes_need_security_rights_and_report_who(client, db_session, team):
    refused = await client.post(
        "/monitoring/rules",
        json={"connection_id": team["connection"], "kind": "security_change"},
        headers=team["a"],
    )
    assert refused.status_code == 403

    users = [SimpleNamespace(name="ana", groups=["Planners"])]
    team["tm1"].security.get_all_users.side_effect = lambda: users
    rule = await _rule(client, team["admin"], team["connection"], "security_change")
    assert await _check(client, team["admin"], rule["id"]) == []

    users = [SimpleNamespace(name="ana", groups=["Planners", "ADMIN"])]
    raised = await _check(client, team["admin"], rule["id"])
    assert raised[0]["severity"] == "critical" and "ADMIN: added ana" in raised[0]["detail"]


@pytest.mark.asyncio
async def test_applied_changes_are_reported(client, db_session, team):
    rule = await _rule(client, team["a"], team["connection"], "deployment")
    change = await _draft(client, team["admin"], team["connection"])
    assert (await _execute(client, team["admin"], team["connection"], change)).status_code == 200

    raised = await _check(client, team["a"], rule["id"])
    assert [a["title"] for a in raised] == ["Applied: update rules on Sales"]


@pytest.mark.asyncio
async def test_the_assistants_rule_waits_for_a_person(client, db_session, team):
    db_session.info.pop("organization_id", None)
    result = json.loads(await ProposeMonitorTool().execute(
        db_session, organization_id=team["org_id"], user_id=team["a_id"],
        connection_id=team["connection"], kind="performance_regression",
        params={"process_name": "Workforce Planning", "factor": 2, "window_days": 30},
        rationale="Alert me if Workforce Planning exceeds 2x its 30-day average.",
    ))
    await db_session.commit()
    assert result["status"] == "proposed"
    rule_id = result["rule_id"]

    not_yet = await client.post(f"/monitoring/rules/{rule_id}/check", headers=team["a"])
    assert not_yet.status_code == 422

    # Only the person who asked (or an admin) turns it on.
    other = await client.patch(f"/monitoring/rules/{rule_id}", json={"status": "active"}, headers=team["b"])
    assert other.status_code == 403
    on = await client.patch(f"/monitoring/rules/{rule_id}", json={"status": "active"}, headers=team["a"])
    assert on.status_code == 200 and on.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_rules_and_alerts_on_a_private_connection_stay_private(client, db_session, team):
    owner = await _user_with(db_session, team["org_id"], "monitoring.view")
    await db_session.commit()
    owner_headers = auth_headers(owner)
    resp = await client.post(
        "/tm1/connections",
        json={"name": "Owner private", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=owner_headers,
    )
    private = resp.json()["data"]["id"]
    rule = await _rule(client, owner_headers, private, "deployment")

    refused = await client.post(
        "/monitoring/rules", json={"connection_id": private, "kind": "deployment"}, headers=team["b"]
    )
    assert refused.status_code == 404
    assert all(r["id"] != rule["id"] for r in
               (await client.get("/monitoring/rules", headers=team["b"])).json()["data"])
    assert (await client.post(f"/monitoring/rules/{rule['id']}/check", headers=team["b"])).status_code == 404


@pytest.mark.asyncio
async def test_an_unreachable_server_is_said_once(client, db_session, team, monkeypatch):
    rule = await _rule(client, team["a"], team["connection"], "dimension_growth", dimension_name="Employee")
    monkeypatch.setattr(tm1_connection_manager, "get_client",
                        AsyncMock(side_effect=ConnectionError("The server could not be reached")))

    results = [await _check(client, team["a"], rule["id"]) for _ in range(5)]

    assert [len(r) for r in results] == [0, 0, 1, 0, 0]
    assert "did not answer 3 times" in results[2][0]["title"]
    listed = (await client.get("/monitoring/rules", headers=team["a"])).json()["data"]
    assert next(r for r in listed if r["id"] == rule["id"])["consecutive_errors"] == 5


@pytest.mark.asyncio
async def test_alerts_are_emailed_to_subscribers(client, db_session, team, monkeypatch):
    sent = []

    class Collector:
        async def send(self, *, to, subject, body):
            sent.append((to, subject, body))

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(monitoring, "get_email_provider", lambda: Collector())

    rule = await _rule(client, team["a"], team["connection"], "process_failure")
    await _check(client, team["a"], rule["id"])
    await _run(db_session, team, "Load Sales", outcome="aborted")
    raised = await _check(client, team["a"], rule["id"])

    assert len(sent) == 1 and "CRITICAL: Load Sales aborted" in sent[0][1]
    assert "nothing was changed" in sent[0][2]
    assert raised[0]["emailed"] is True


@pytest.mark.asyncio
async def test_the_schedule_endpoint_needs_the_cron_secret(client):
    assert (await client.post("/internal/cron/monitors")).status_code == 401
    assert (await client.get("/internal/cron/monitors", headers={"Authorization": "Bearer wrong"})).status_code == 401


@pytest.mark.asyncio
async def test_a_scheduled_pass_checks_due_active_rules_only(client, db_session, team, monkeypatch):
    import contextlib

    import src.database.session as session_module

    @contextlib.asynccontextmanager
    async def same_session():
        yield db_session

    monkeypatch.setattr(session_module, "AsyncSessionLocal", same_session)
    db_session.info.pop("organization_id", None)

    active = await _rule(client, team["a"], team["connection"], "process_failure")
    await _check(client, team["a"], active["id"])  # checked just now: not due yet
    paused = await _rule(client, team["a"], team["connection"], "deployment")
    await client.patch(f"/monitoring/rules/{paused['id']}", json={"status": "paused"}, headers=team["a"])
    due = await _rule(client, team["a"], team["connection"], "deployment")  # never checked: due

    result = await monitoring.run_due_monitors()

    assert result["checked"] == 1 and result["failed"] == 0
    listed = {r["id"]: r for r in (await client.get("/monitoring/rules", headers=team["a"])).json()["data"]}
    assert listed[due["id"]]["last_checked_at"] is not None
    assert listed[paused["id"]]["last_checked_at"] is None
