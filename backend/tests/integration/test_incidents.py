"""Incident mode: report what looks wrong, see what changed, act through
governed changes, look again to see it cleared.

The faked server is the extractor's model: Load Sales reads Expense and
writes Sales; Sales's rules read Expense.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.ai.tools.incidents import InvestigateIncidentTool
from src.database.models.tm1_health import TM1ProcessRun
from src.tm1.metadata.history import run_extraction
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_environments import _user_with
from tests.unit.tm1.test_extractor import fake_tm1_client, tm1_credentials_key  # noqa: F401 - fixtures


@pytest.fixture
async def model(db_session, tm1_credentials_key, fake_tm1_client):  # noqa: F811
    fake_tm1_client.server.get_message_log_entries.return_value = []
    fake_tm1_client.cubes.check_rules.return_value = []
    org, admin = await create_org_admin(db_session)
    org_id, admin_id = org.id, admin.id
    connection = await tm1_integration_service.create_connection(
        db_session, organization_id=org_id, created_by=admin_id, name="Planning PROD", address="tm1.example.com",
        port=8010, ssl=True, username="admin", password="secret",
    )
    connection.environment, connection.visibility = "prod", "organization"
    await db_session.flush()
    await run_extraction(db_session, connection.id, org_id, trigger="manual")
    await db_session.commit()
    return {"org_id": org_id, "admin_id": admin_id, "headers": auth_headers(admin), "connection": connection.id}


async def _report(client, headers, connection, **extra):
    body = {"reference": extra.pop("reference", "INC-1"), "title": "Production allocation is wrong",
            "connection_id": str(connection), "severity": "high", **extra}
    return await client.post("/team/incidents", json=body, headers=headers)


async def _failed_run(db_session, model, process="Load Sales"):
    db_session.add(TM1ProcessRun(
        id=uuid.uuid4(), connection_id=model["connection"], organization_id=model["org_id"],
        process_name=process, finished_at=datetime.now(timezone.utc) - timedelta(hours=1),
        elapsed_seconds=12, outcome="aborted", source="message_log",
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_a_rule_change_and_a_failed_writer_are_the_suspects_and_a_rollback_clears_one(
    client, db_session, model
):
    approver = await _user_with(db_session, model["org_id"], "tm1.deploy", "tm1.deploy.prod")
    await db_session.commit()
    # A rules change applied on the cube today (PROD: drafted by one person, applied by another).
    draft = await client.post(
        f"/tm1/connections/{model['connection']}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['Total'] = N: 0;"}},
        headers=model["headers"],
    )
    change = draft.json()["data"]["id"]
    applied = await client.post(f"/tm1/connections/{model['connection']}/changes/{change}/execute",
                                json={"acknowledge_impact": True}, headers=auth_headers(approver))
    assert applied.status_code == 200, applied.text
    await _failed_run(db_session, model)

    resp = await _report(client, model["headers"], model["connection"], cube_name="Sales")
    assert resp.status_code == 201, resp.text
    detail = resp.json()["data"]
    assert detail["item"]["kind"] == "incident" and detail["item"]["severity"] == "high"
    look = detail["investigations"][0]["findings"]

    assert look["environment"] == "prod"
    assert look["affected"]["writers"]["Sales"] == ["Load Sales"]
    assert "Expense" in look["affected"]["rule_sources"]
    top = look["suspects"][0]
    assert top["title"] == "Applied: update rules on Sales"
    assert top["mitigation"] == {"action": "rollback", "label": "Roll back this change (update rules on Sales)",
                                 "change_id": change}
    assert any(s["kind"] == "run_failed" and "Load Sales" in s["title"] for s in look["suspects"]), look
    assert "only read" in look["applied_nothing"]

    # The mitigation is a person's governed rollback; then look again.
    rolled = await client.post(f"/tm1/connections/{model['connection']}/changes/{change}/rollback",
                               headers=auth_headers(approver))
    assert rolled.status_code == 200, rolled.text
    again = await client.post(f"/team/work-items/{detail['item']['id']}/investigate", headers=model["headers"])
    assert again.status_code == 200, again.text
    second = again.json()["data"]
    assert all(s["kind"] != "change" for s in second["investigations"][0]["findings"]["suspects"])
    assert len(second["investigations"]) == 2
    assert [e["title"] for e in second["events"]].count("Investigated") == 2


@pytest.mark.asyncio
async def test_a_failed_process_is_traced_to_the_cubes_it_writes(client, db_session, model):
    await _failed_run(db_session, model)

    resp = await _report(client, model["headers"], model["connection"], process_name="Load Sales")
    look = resp.json()["data"]["investigations"][0]["findings"]

    assert look["affected"]["cubes"] == ["Sales"]
    assert look["suspects"][0]["mitigation"]["action"] == "diagnose"


@pytest.mark.asyncio
async def test_nothing_found_says_so(client, model):
    resp = await _report(client, model["headers"], model["connection"], cube_name="Expense")
    look = resp.json()["data"]["investigations"][0]["findings"]
    assert look["suspects"] == [], look
    assert look["summary"].startswith("Nothing changed, failed or differed")


@pytest.mark.asyncio
async def test_an_incident_needs_a_cube_or_a_process(client, model):
    resp = await _report(client, model["headers"], model["connection"])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_investigations_follow_the_connection(client, db_session, model):
    owner = auth_headers(await _user_with(db_session, model["org_id"], "ai.chat"))
    other = auth_headers(await _user_with(db_session, model["org_id"], "ai.chat"))
    await db_session.commit()
    created = await client.post(
        "/tm1/connections",
        json={"name": "Owner private", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=owner,
    )
    private = created.json()["data"]["id"]

    assert (await _report(client, other, private, cube_name="Sales",
                          reference="INC-X")).status_code == 404

    reported = await _report(client, owner, private, cube_name="Sales", reference="INC-2")
    assert reported.status_code == 201, reported.text
    item = reported.json()["data"]["item"]["id"]
    seen = (await client.get(f"/team/work-items/{item}", headers=other)).json()["data"]
    assert seen["investigations"] is None
    assert "Investigated" not in [e["title"] for e in seen["events"]]
    assert (await client.post(f"/team/work-items/{item}/investigate", headers=other)).status_code == 404


@pytest.mark.asyncio
async def test_the_assistant_investigates_without_saving(client, db_session, model):
    await _failed_run(db_session, model)
    db_session.info.pop("organization_id", None)

    found = json.loads(await InvestigateIncidentTool().execute(
        db_session, organization_id=model["org_id"], user_id=model["admin_id"],
        connection_id=str(model["connection"]), cube_name="Sales",
    ))
    assert found["suspects"] and found["environment"] == "prod"
    listed = (await client.get("/team/work-items", headers=model["headers"])).json()["data"]
    assert listed == []
