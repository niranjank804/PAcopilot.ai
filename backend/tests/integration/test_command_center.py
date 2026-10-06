"""The Command Center: every section from recorded data, limited to the
servers this person may use."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.database.models.monitor import MonitorAlert, MonitorRule
from src.database.models.tm1_health import TM1HealthScan, TM1ProcessRun
from src.database.models.work_item import WorkItem
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection, _draft, _execute, _user_with


@pytest.mark.asyncio
async def test_each_section_shows_what_needs_attention(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    org_id, admin_id = org.id, admin.id
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    dev_id = uuid.UUID(dev)
    now = datetime.now(timezone.utc)

    applied = await _draft(client, headers, dev)
    assert (await _execute(client, headers, dev, applied)).status_code == 200
    db_session.add_all([
        TM1HealthScan(connection_id=dev_id, organization_id=org_id, trigger="manual", scanned_at=now,
                      score=72, grade="C", totals={},
                      deductions=[{"category": "failed_processes", "label": "Processes that failed",
                                   "count": 2, "points": 4.0, "evidence": []}]),
        TM1ProcessRun(connection_id=dev_id, organization_id=org_id, process_name="Load Sales",
                      finished_at=now - timedelta(hours=2), elapsed_seconds=5, outcome="aborted",
                      source="message_log"),
        WorkItem(organization_id=org_id, reference="INC-1", title="Allocation is wrong", status="open",
                 kind="incident", severity="high", connection_id=dev_id, cube_name="Sales", created_by=admin_id),
    ])
    rule = MonitorRule(organization_id=org_id, connection_id=dev_id, name="Fails", kind="process_failure",
                       params={}, status="active", source="human", interval_minutes=15, notify=[],
                       created_by=admin_id, consecutive_errors=0)
    db_session.add(rule)
    await db_session.flush()
    db_session.add(MonitorAlert(organization_id=org_id, rule_id=rule.id, connection_id=dev_id,
                                severity="critical", title="Load Sales aborted", dedup_key="x",
                                fired_at=now, status="open"))
    await db_session.commit()
    pending = await _draft(client, headers, dev)  # a second draft, waiting

    resp = await client.get("/command-center", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["health"][0]["score"] == 72
    assert data["risks"][0]["category"] == "failed_processes"
    assert [i["reference"] for i in data["incidents"]] == ["INC-1"]
    assert data["failed_processes"][0]["process"] == "Load Sales"
    assert data["alerts"]["critical"] == 1
    assert [c["id"] for c in data["pending_approvals"]] == [pending]
    assert any(c["id"] == applied and c["status"] == "executed" for c in data["deployments"])
    assert data["ai"]["days"] == 30


@pytest.mark.asyncio
async def test_a_private_server_stays_out(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    owner = await _user_with(db_session, org.id, "monitoring.view")
    other = await _user_with(db_session, org.id, "monitoring.view")
    await db_session.commit()
    owner_headers, other_headers = auth_headers(owner), auth_headers(other)
    created = await client.post(
        "/tm1/connections",
        json={"name": "Owner private", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=owner_headers,
    )
    private = created.json()["data"]["id"]
    draft = await _draft(client, owner_headers, private)

    mine = (await client.get("/command-center", headers=owner_headers)).json()["data"]
    theirs = (await client.get("/command-center", headers=other_headers)).json()["data"]

    assert [c["id"] for c in mine["pending_approvals"]] == [draft]
    assert theirs["pending_approvals"] == [] and theirs["servers"] == 0
