"""The write paths, against a real TM1 DEV server.

Everything else in tests/live/ only reads. These tests write — but only to
objects they create themselves, named `zzPACopilotLive_<random>`, and they
remove them afterwards whether the test passed or not. Nothing that exists
on the server is read-modified-written.

They run only when you ask, twice over:

    TM1_LIVE_WRITE=1
    TM1_LIVE_WRITE_SERVER=<the server's name, exactly as TM1 reports it>

The second must match the name the server reports, so pointing the
variables at the wrong server (a PROD one) makes every test here skip
instead of writing to it. Use a DEV server.

What is checked, through PA-Copilot's own change engine (draft → apply →
verify → rollback), on the real server:

* a new process is compiled by TM1 before it is saved, and a broken one is
  refused at draft time without touching the server;
* create, update, run, delete — and rollback of update and delete;
* cell writes: leaf cells written and read back, consolidated and
  rule-calculated cells refused, a value changed since the draft refuses
  the apply, rollback writes the old values back;
* rules: applied, checked by TM1, the rule-calculated cell reported as
  such, and rolled back;
* a run that fails is recorded as failed with TM1's status.
"""

import asyncio
import os
import uuid

import pytest
from TM1py import Cube, Dimension, Hierarchy

from src.core.exceptions import ConflictException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.deployment.change_service import change_service
from src.tm1.services import cell_service

pytestmark = pytest.mark.live


@pytest.fixture
async def dev(db_session, live_connection):
    """The live connection, after both opt-ins are confirmed against the
    server itself."""

    if os.environ.get("TM1_LIVE_WRITE") != "1":
        pytest.skip("TM1_LIVE_WRITE=1 not set — write-path tests skipped")
    expected = os.environ.get("TM1_LIVE_WRITE_SERVER")
    if not expected:
        pytest.skip("TM1_LIVE_WRITE_SERVER not set — write-path tests skipped")

    org, user, connection = live_connection
    connection.environment = "dev"
    await db_session.flush()
    tm1 = await tm1_connection_manager.get_client(connection)
    actual = await asyncio.to_thread(tm1.server.get_server_name)
    if actual != expected:
        pytest.skip(f"Server is '{actual}', not '{expected}' — refusing to write to it")

    return {"org": org, "user": user, "connection": connection, "tm1": tm1,
            "prefix": f"zzPACopilotLive_{uuid.uuid4().hex[:6]}"}


async def _draft(db_session, dev, change_type, target, content):
    return await change_service.create_change(
        db_session, connection_id=dev["connection"].id, organization_id=dev["org"].id,
        created_by=dev["user"].id, change_type=change_type, target_name=target, new_content=content,
    )


async def _apply(db_session, dev, change):
    return await change_service.execute_change(db_session, change, dev["user"].id, acknowledge_impact=True)


async def _quietly(fn, *args):
    try:
        await asyncio.to_thread(fn, *args)
    except Exception:  # noqa: BLE001 - cleanup of something that may not exist
        pass


@pytest.mark.asyncio
async def test_a_broken_process_is_refused_before_it_is_saved(db_session, dev):
    name = f"{dev['prefix']}_Broken"
    try:
        draft = await _draft(db_session, dev, "create_process", name, {"prolog": "nValue = ;\n"})

        assert draft.validation_errors, "TM1 should have refused to compile it"
        assert not await asyncio.to_thread(dev["tm1"].processes.exists, name)
    finally:
        await _quietly(dev["tm1"].processes.delete, name)


@pytest.mark.asyncio
async def test_process_create_update_run_delete_and_rollbacks(db_session, dev):
    name = f"{dev['prefix']}_Process"
    tm1 = dev["tm1"]
    try:
        created = await _apply(db_session, dev, await _draft(
            db_session, dev, "create_process", name, {"prolog": "nCount = 1;\n"}))
        assert created.status == "executed", created.error_message
        assert await asyncio.to_thread(tm1.processes.exists, name)

        updated = await _apply(db_session, dev, await _draft(
            db_session, dev, "update_process", name, {"prolog": "nCount = 2;\n"}))
        assert updated.status == "executed", updated.error_message
        assert "nCount = 2;" in (await asyncio.to_thread(tm1.processes.get, name)).prolog_procedure

        ran = await _apply(db_session, dev, await _draft(db_session, dev, "run_process", name, {"parameters": {}}))
        assert ran.status == "executed", ran.error_message
        assert ran.execution_result["success"] is True

        rolled = await change_service.rollback_change(db_session, updated)
        assert rolled.status == "rolled_back"
        assert "nCount = 1;" in (await asyncio.to_thread(tm1.processes.get, name)).prolog_procedure

        deleted = await _apply(db_session, dev, await _draft(db_session, dev, "delete_process", name, None))
        assert deleted.status == "executed"
        assert not await asyncio.to_thread(tm1.processes.exists, name)

        restored = await change_service.rollback_change(db_session, deleted)
        assert restored.status == "rolled_back"
        assert await asyncio.to_thread(tm1.processes.exists, name)
    finally:
        await _quietly(tm1.processes.delete, name)


@pytest.mark.asyncio
async def test_a_failing_run_is_recorded_as_failed(db_session, dev):
    name = f"{dev['prefix']}_Fails"
    try:
        await _apply(db_session, dev, await _draft(
            db_session, dev, "create_process", name, {"prolog": "ProcessError;\n"}))

        ran = await _apply(db_session, dev, await _draft(db_session, dev, "run_process", name, {"parameters": {}}))

        assert ran.status == "failed"
        assert ran.execution_result["success"] is False
        assert ran.execution_result["status"]  # TM1's own word for it, e.g. Aborted
    finally:
        await _quietly(dev["tm1"].processes.delete, name)


@pytest.fixture
async def scratch_cube(dev):
    """Item (A, B, Total = A + B) × Measure (Value numeric, Note string)."""

    tm1, prefix = dev["tm1"], dev["prefix"]
    item, measure, cube = f"{prefix}_Item", f"{prefix}_Measure", f"{prefix}_Cube"

    h = Hierarchy(item, item)
    for element, kind in (("A", "Numeric"), ("B", "Numeric"), ("Total", "Consolidated")):
        h.add_element(element, kind)
    h.add_edge("Total", "A", 1)
    h.add_edge("Total", "B", 1)
    m = Hierarchy(measure, measure)
    m.add_element("Value", "Numeric")
    m.add_element("Note", "String")

    await asyncio.to_thread(tm1.dimensions.create, Dimension(item, [h]))
    await asyncio.to_thread(tm1.dimensions.create, Dimension(measure, [m]))
    await asyncio.to_thread(tm1.cubes.create, Cube(cube, [item, measure]))
    try:
        yield cube
    finally:
        await _quietly(tm1.cubes.delete, cube)
        await _quietly(tm1.dimensions.delete, item)
        await _quietly(tm1.dimensions.delete, measure)


async def _values(dev, cube, coordinates):
    result = await cell_service.read_cells(dev["tm1"], dev["connection"].id, cube, coordinates)
    return result["cells"]


@pytest.mark.asyncio
async def test_cell_writes_apply_verify_refuse_and_roll_back(db_session, dev, scratch_cube):
    cube = scratch_cube

    refused = await _draft(db_session, dev, "write_cells", cube, {"cells": [
        {"coordinates": ["Total", "Value"], "value": 9},
        {"coordinates": ["A", "Note"], "value": 3},
    ]})
    errors = " | ".join(refused.validation_errors or [])
    assert "consolidated" in errors and "string cell" in errors, errors

    change = await _draft(db_session, dev, "write_cells", cube, {"cells": [
        {"coordinates": ["A", "Value"], "value": 5},
        {"coordinates": ["B", "Value"], "value": 7},
        {"coordinates": ["A", "Note"], "value": "checked"},
    ]})
    assert not change.validation_errors, change.validation_errors
    applied = await _apply(db_session, dev, change)
    assert applied.status == "executed", applied.error_message
    cells = await _values(dev, cube, [["A", "Value"], ["B", "Value"], ["Total", "Value"], ["A", "Note"]])
    assert [c["value"] for c in cells] == [5, 7, 12, "checked"]

    rolled = await change_service.rollback_change(db_session, applied)
    assert rolled.status == "rolled_back"
    cells = await _values(dev, cube, [["A", "Value"], ["B", "Value"]])
    assert [c["value"] or 0 for c in cells] == [0, 0]


@pytest.mark.asyncio
async def test_a_value_changed_after_the_draft_refuses_the_apply(db_session, dev, scratch_cube):
    cube = scratch_cube
    change = await _draft(db_session, dev, "write_cells", cube, {"cells": [{"coordinates": ["A", "Value"], "value": 5}]})
    await asyncio.to_thread(dev["tm1"].cells.write_value, 3, cube, ("A", "Value"))

    with pytest.raises(ConflictException):
        await _apply(db_session, dev, change)
    cells = await _values(dev, cube, [["A", "Value"]])
    assert cells[0]["value"] == 3


@pytest.mark.asyncio
async def test_rules_apply_are_checked_and_roll_back(db_session, dev, scratch_cube):
    cube = scratch_cube
    applied = await _apply(db_session, dev, await _draft(
        db_session, dev, "update_rules", cube, {"rules": "SKIPCHECK;\n['B','Value'] = N: 42;\n"}))
    assert applied.status == "executed", applied.error_message

    cell = (await _values(dev, cube, [["B", "Value"]]))[0]
    assert cell["value"] == 42 and cell["rule_derived"], cell

    refused = await _draft(db_session, dev, "write_cells", cube, {"cells": [{"coordinates": ["B", "Value"], "value": 1}]})
    assert "calculated by a rule" in " ".join(refused.validation_errors or [])

    rolled = await change_service.rollback_change(db_session, applied)
    assert rolled.status == "rolled_back"
    cell = (await _values(dev, cube, [["B", "Value"]]))[0]
    assert not cell["rule_derived"]
