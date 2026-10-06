"""The governed workflow, against a real TM1 DEV/test server.

Every write goes through PA-Copilot's own HTTP API and permission checks, as
two disposable users in a disposable organization: an author who drafts
(tm1.write, no deploy right) and an approver who applies (tm1.deploy). The
connection is created through the API, so its password is stored the way
the product stores it — encrypted, in the local test database, inside the
test's transaction, which is rolled back afterwards.

TM1 is touched directly (TM1py) only to provision run-owned fixtures and to
verify results independently of PA-Copilot's code. Nothing that existed
before the run is read-modified-written; see OwnedFixtures in conftest.py.

Writes need the authorization in conftest.write_target. Without it every
test here is BLOCKED before anything is sent.
"""

import pytest
from sqlalchemy import select
from TM1py import Cube, Dimension, Hierarchy, Process

from src.database.models.audit_log import AuditLog
from tests.fixtures.factories import auth_headers, create_organization
from tests.integration.tm1.test_environments import _user_with

pytestmark = [pytest.mark.live, pytest.mark.live_write]


@pytest.fixture
async def gov(client, db_session, live_credentials_key, live_tm1_config, write_target):
    org = await create_organization(db_session)
    author = await _user_with(db_session, org.id)  # tm1.read + tm1.write: drafts, cannot apply
    approver = await _user_with(db_session, org.id, "tm1.deploy")
    ids = {"author_id": str(author.id), "approver_id": str(approver.id)}
    headers = {"author": auth_headers(author), "approver": auth_headers(approver)}
    await db_session.commit()

    cfg = live_tm1_config
    resp = await client.post(
        "/tm1/connections",
        json={"name": "Live validation", "address": cfg["address"], "port": cfg["port"], "ssl": cfg["ssl"],
              "username": cfg["username"], "password": cfg["password"], "environment": "dev",
              "visibility": "organization"},
        headers=headers["author"],
    )
    assert resp.status_code == 201, "creating the connection through the API failed"
    return {"conn": resp.json()["data"]["id"], **headers, **ids}


async def _draft(client, gov, change_type, target, content):
    resp = await client.post(
        f"/tm1/connections/{gov['conn']}/changes",
        json={"change_type": change_type, "target_name": target, "new_content": content},
        headers=gov["author"],
    )
    assert resp.status_code == 201, resp.json().get("error")
    return resp.json()["data"]


async def _apply(client, gov, change_id, *, as_who="approver"):
    return await client.post(
        f"/tm1/connections/{gov['conn']}/changes/{change_id}/execute",
        json={"acknowledge_impact": True}, headers=gov[as_who],
    )


async def _rollback(client, gov, change_id):
    return await client.post(f"/tm1/connections/{gov['conn']}/changes/{change_id}/rollback",
                             headers=gov["approver"])


async def _audited(db_session, change_id, action, user_id) -> bool:
    rows = (await db_session.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    return any((r.new_values or {}).get("change_id") == change_id and str(r.user_id) == user_id for r in rows)


def _prolog(tm1, name) -> str:
    return tm1.processes.get(name).prolog_procedure


@pytest.mark.asyncio
async def test_process_definition_lifecycle(client, db_session, gov, owned, direct_tm1, live_run, record_property):
    record_property("layer", "C: governed workflow (API)")
    record_property("transport", "DIRECT")
    tm1, name = direct_tm1, live_run.name("Proc")
    assert not tm1.processes.exists(name)

    created = await _draft(client, gov, "create_process", name, {"prolog": "nCount = 1;\n"})
    assert not tm1.processes.exists(name), "a draft must not touch TM1"
    assert (await _apply(client, gov, created["id"], as_who="author")).status_code == 403
    applied = await _apply(client, gov, created["id"])
    assert applied.status_code == 200 and applied.json()["data"]["status"] == "executed"
    assert tm1.processes.exists(name)
    owned.confirm_created_by_product("process", name)
    assert applied.json()["data"]["executed_by"] == gov["approver_id"]
    assert await _audited(db_session, created["id"], "execute_change", gov["approver_id"])

    updated = await _draft(client, gov, "update_process", name, {"prolog": "nCount = 2;\n"})
    assert (await _apply(client, gov, updated["id"])).status_code == 200
    assert "nCount = 2;" in _prolog(tm1, name)

    rolled = await _rollback(client, gov, updated["id"])
    assert rolled.status_code == 200 and rolled.json()["data"]["status"] == "rolled_back"
    assert "nCount = 1;" in _prolog(tm1, name)
    assert await _audited(db_session, updated["id"], "rollback_change", gov["approver_id"])

    deleted = await _draft(client, gov, "delete_process", name, None)
    assert (await _apply(client, gov, deleted["id"])).status_code == 200
    assert not tm1.processes.exists(name)
    assert (await _rollback(client, gov, deleted["id"])).status_code == 200
    assert tm1.processes.exists(name) and "nCount = 1;" in _prolog(tm1, name)
    record_property("observed", "create, update, rollback, delete, restore: all verified directly")


@pytest.mark.asyncio
async def test_process_execution_and_a_safe_failure(client, gov, owned, direct_tm1, live_run, record_property):
    record_property("layer", "C: governed workflow (API)")
    record_property("transport", "DIRECT")
    tm1 = direct_tm1
    ok, bad = live_run.name("RunOk"), live_run.name("RunFail")
    # Reviewed fixtures: they touch nothing — no cube, file, or command.
    owned.create("process", ok, lambda: tm1.processes.create(Process(name=ok, prolog_procedure="nX = 1;\n")))
    owned.create("process", bad, lambda: tm1.processes.create(Process(name=bad, prolog_procedure="ProcessError;\n")))

    run = await _draft(client, gov, "run_process", ok, {"parameters": {}})
    done = (await _apply(client, gov, run["id"])).json()["data"]
    assert done["status"] == "executed" and done["execution_result"]["success"] is True

    failing = await _draft(client, gov, "run_process", bad, {"parameters": {}})
    failed = (await _apply(client, gov, failing["id"])).json()["data"]
    assert failed["status"] == "failed", "a failing run must never be recorded as a success"
    assert failed["execution_result"]["success"] is False and failed["execution_result"]["status"]
    record_property("compat_path", done["execution_result"].get("api"))
    record_property("observed", f"run ok; failing run recorded as {failed['execution_result']['status']}")


@pytest.mark.asyncio
async def test_compile_without_save(client, db_session, gov, owned, direct_tm1, live_run, monkeypatch, record_property):
    """The product path for compile-without-save is the agents' tool, run
    through the real tool dispatcher with its permission checks — no AI call."""

    record_property("layer", "B: service/tool path")
    record_property("transport", "DIRECT")
    import json
    import uuid

    from src.ai.orchestrator import ai_orchestrator
    from src.ai.schemas import ToolCall
    from src.database.models.ai_conversation import AIConversation
    from src.database.models.tm1_connection import TM1Connection
    from src.tm1.client.connection_manager import tm1_connection_manager

    tm1, name = direct_tm1, live_run.name("Compile")
    owned.create("process", name, lambda: tm1.processes.create(Process(name=name, prolog_procedure="nX = 1;\n")))
    before = tm1.processes.get(name).body_as_dict

    # Any save through the product's own client during the check fails the test.
    connection = await db_session.get(TM1Connection, uuid.UUID(gov["conn"]))
    product_client = await tm1_connection_manager.get_client(connection)

    def no_save(*_args, **_kwargs):
        raise AssertionError("compile-without-save sent a save")

    for method in ("update", "update_or_create", "create", "delete"):
        monkeypatch.setattr(product_client.processes, method, no_save)

    conversation = AIConversation(organization_id=connection.organization_id, user_id=uuid.UUID(gov["author_id"]),
                                  title="compile check")
    db_session.add(conversation)
    await db_session.flush()
    db_session.info.pop("organization_id", None)

    async def check(prolog):
        result = await ai_orchestrator._execute_tool_call(
            db_session,
            ToolCall(id="c", name="validate_process_code",
                     input={"connection_id": gov["conn"], "process_name": name, "prolog": prolog}),
            organization_id=connection.organization_id, user_id=uuid.UUID(gov["author_id"]),
            conversation_id=conversation.id, allowed_tools=None, agent=None,
        )
        return json.loads(result.content)

    valid = await check("nX = 2;\n")
    invalid = await check("nX = ;\n")
    assert valid.get("valid") is True, valid
    assert invalid.get("valid") is False, invalid
    assert tm1.processes.get(name).body_as_dict == before, "the stored definition changed"
    record_property("observed", "valid and invalid code checked; stored definition unchanged; no save sent")


@pytest.fixture
def cube(owned, direct_tm1, live_run):
    """Item (A, B, Total = A + B) x Measure (Value numeric, Note string)."""

    tm1 = direct_tm1
    item, measure, cube_name = live_run.name("Item"), live_run.name("Measure"), live_run.name("Cube")
    h = Hierarchy(item, item)
    for element, kind in (("A", "Numeric"), ("B", "Numeric"), ("Total", "Consolidated")):
        h.add_element(element, kind)
    h.add_edge("Total", "A", 1)
    h.add_edge("Total", "B", 1)
    m = Hierarchy(measure, measure)
    m.add_element("Value", "Numeric")
    m.add_element("Note", "String")
    owned.create("dimension", item, lambda: tm1.dimensions.create(Dimension(item, [h])))
    owned.create("dimension", measure, lambda: tm1.dimensions.create(Dimension(measure, [m])))
    owned.create("cube", cube_name, lambda: tm1.cubes.create(Cube(cube_name, [item, measure])))
    return cube_name


def _value(tm1, cube_name, *coordinates):
    return tm1.cells.get_value(cube_name, ",".join(coordinates))


def _cells(*pairs):
    return {"cells": [{"coordinates": list(c), "value": v} for c, v in pairs]}


@pytest.mark.asyncio
async def test_cell_writes_refusals_drift_and_rollback(client, db_session, gov, cube, direct_tm1, record_property):
    record_property("layer", "C: governed workflow (API)")
    record_property("transport", "DIRECT")
    tm1 = direct_tm1
    baseline = {c: _value(tm1, cube, *c) for c in (("A", "Value"), ("B", "Value"), ("Total", "Value"))}

    for refused_content, expect in (
        (_cells((("Nope", "Value"), 1)), "do not exist"),
        (_cells((("A", "Value", "Extra"), 1)), "one element per"),
        (_cells((("Total", "Value"), 9)), "consolidated"),
        (_cells((("A", "Note"), 3)), "string cell"),
        (_cells((("A", "Value"), 1), (("A", "Value"), 2)), "more than once"),
    ):
        draft = await _draft(client, gov, "write_cells", cube, refused_content)
        assert any(expect in e for e in draft["validation_errors"] or []), (expect, draft["validation_errors"])
        assert (await _apply(client, gov, draft["id"])).status_code == 422
    too_many = await client.post(
        f"/tm1/connections/{gov['conn']}/changes",
        json={"change_type": "write_cells", "target_name": cube,
              "new_content": _cells(*[(("A", "Value"), i) for i in range(201)])},
        headers=gov["author"],
    )
    assert too_many.status_code == 422
    assert {c: _value(tm1, cube, *c) for c in baseline} == baseline, "a refused write changed cells"

    write = await _draft(client, gov, "write_cells", cube, _cells((("A", "Value"), 5), (("B", "Value"), 7)))
    applied = await _apply(client, gov, write["id"])
    assert applied.status_code == 200 and applied.json()["data"]["status"] == "executed"
    assert (_value(tm1, cube, "A", "Value"), _value(tm1, cube, "B", "Value"), _value(tm1, cube, "Total", "Value")) == (5, 7, 12)
    assert await _audited(db_session, write["id"], "execute_change", gov["approver_id"])

    stale = await _draft(client, gov, "write_cells", cube, _cells((("A", "Value"), 6)))
    tm1.cells.write_value(4, cube, ("A", "Value"))  # someone types in it meanwhile
    assert (await _apply(client, gov, stale["id"])).status_code == 409
    assert _value(tm1, cube, "A", "Value") == 4

    # Rollback refuses to overwrite the newer value...
    assert (await _rollback(client, gov, write["id"])).status_code == 409
    assert _value(tm1, cube, "A", "Value") == 4
    # ...and restores the saved values once nothing newer is there.
    tm1.cells.write_value(5, cube, ("A", "Value"))
    rolled = await _rollback(client, gov, write["id"])
    assert rolled.status_code == 200
    assert (_value(tm1, cube, "A", "Value") or 0, _value(tm1, cube, "B", "Value") or 0) == (
        baseline[("A", "Value")] or 0, baseline[("B", "Value")] or 0)
    record_property("observed", "5 refusals, limit, drift and rollback-over-newer refused; write and restore verified")


@pytest.mark.asyncio
async def test_rules_apply_check_refuse_and_roll_back(client, gov, cube, direct_tm1, record_property):
    record_property("layer", "C: governed workflow (API)")
    record_property("transport", "DIRECT")
    tm1 = direct_tm1
    baseline = tm1.cubes.get(cube).rules
    baseline_text = baseline.text if baseline else ""

    bad = await _draft(client, gov, "update_rules", cube, {"rules": "['B','Value'] = N: ;"})
    refused = await _apply(client, gov, bad["id"])
    assert refused.status_code >= 400, "invalid rule syntax must not be applied"
    current = tm1.cubes.get(cube).rules
    assert (current.text if current else "") == baseline_text, "the last valid rules were not preserved"

    good = await _draft(client, gov, "update_rules", cube, {"rules": "SKIPCHECK;\n['B','Value'] = N: 42;\n"})
    applied = await _apply(client, gov, good["id"])
    assert applied.status_code == 200 and applied.json()["data"]["status"] == "executed"
    assert "N: 42" in tm1.cubes.get(cube).rules.text
    assert _value(tm1, cube, "B", "Value") == 42
    blocked = await _draft(client, gov, "write_cells", cube, _cells((("B", "Value"), 1)))
    assert any("rule" in e for e in blocked["validation_errors"] or [])

    assert (await _rollback(client, gov, good["id"])).status_code == 200
    restored = tm1.cubes.get(cube).rules
    assert (restored.text if restored else "").strip() == baseline_text.strip()
    record_property("observed", "invalid syntax refused, last state kept; rule applied, calculated, rolled back")
