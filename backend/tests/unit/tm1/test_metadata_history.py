"""The dependency map's history and freshness (phase 2).

The map is rebuilt on every extraction; these tests pin what is kept
around it: what changed between two extractions, how old the map is, the
links to views and subsets, and the one-process refresh that keeps the map
in step with a change PA-Copilot applied.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from src.ai.tools.tm1.analysis import GetModelChangesTool
from src.database.models.tm1_object import TM1Object
from src.tm1.metadata import extractor, history
from src.tm1.metadata.history import diff_graphs, graph_freshness, graph_keys, run_extraction
from tests.fixtures.factories import create_org_admin, create_organization, create_user
from tests.unit.tm1.test_extractor import (  # noqa: F401 - fixtures
    _create_connection,
    _make_process,
    fake_tm1_client,
    tm1_credentials_key,
)


def test_a_diff_names_what_appeared_and_disappeared():
    before = ({("cube", "Sales"), ("process", "Old Load")},
              {("process", "Old Load", "updates_cube", "cube", "Sales")})
    after = ({("cube", "Sales"), ("process", "New Load")},
             {("process", "New Load", "updates_cube", "cube", "Sales")})

    changes = diff_graphs(before, after)

    assert changes["first"] is False
    assert changes["objects_added"] == [{"type": "process", "name": "New Load"}]
    assert changes["objects_removed"] == [{"type": "process", "name": "Old Load"}]
    assert changes["counts"]["relationships_added"] == 1
    assert changes["relationships_removed"][0]["from"] == "process:Old Load"


def test_the_first_extraction_does_not_call_everything_new():
    changes = diff_graphs((set(), set()), ({("cube", "Sales")}, set()))

    assert changes["first"] is True
    assert changes["objects_added"] == []
    assert changes["counts"]["objects_added"] == 1


@pytest.mark.asyncio
async def test_each_extraction_is_recorded_with_what_changed(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    _, first = await run_extraction(db_session, connection.id, org.id, trigger="manual", triggered_by=user.id)
    assert first.status == "succeeded" and first.changes["first"] is True

    # In TM1, the process now also writes Expense.
    fake_tm1_client.processes.get.return_value = _make_process(
        "Load Sales",
        datasource_type="TM1CubeView",
        datasource_name="Expense",
        data_code="CellPutN(1, 'Sales', 'NA'); CellPutN(1, 'Expense', 'NA');",
    )
    _, second = await run_extraction(db_session, connection.id, org.id, trigger="schedule")

    added = second.changes["relationships_added"]
    assert {"from": "process:Load Sales", "relationship": "updates_cube", "to": "cube:Expense"} in added
    assert second.trigger == "schedule"
    assert [r.id for r in await history.list_extractions(db_session, connection.id, org.id)] == [second.id, first.id]


@pytest.mark.asyncio
async def test_the_map_says_how_old_it_is(db_session, tm1_credentials_key, fake_tm1_client):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    assert (await graph_freshness(db_session, connection.id))["extracted_at"] is None

    await run_extraction(db_session, connection.id, org.id, trigger="manual")
    fresh = await graph_freshness(db_session, connection.id)
    assert fresh["age_days"] < 1 and "note" not in fresh

    await db_session.execute(
        update(TM1Object)
        .where(TM1Object.connection_id == connection.id)
        .values(extracted_at=datetime.now(timezone.utc) - timedelta(days=30))
    )
    stale = await graph_freshness(db_session, connection.id)
    assert "30 days old" in stale["note"]


@pytest.mark.asyncio
async def test_a_process_change_updates_only_that_process_in_the_map(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")
    _, before_edges = await graph_keys(db_session, connection.id)

    fake_tm1_client.processes.get.return_value = _make_process(
        "Load Sales", datasource_type="None", datasource_name="",
        data_code="CellPutN(1, 'Expense', 'NA');",
    )
    assert await extractor.refresh_process(db_session, connection.id, org.id, "Load Sales")

    _, after_edges = await graph_keys(db_session, connection.id)
    assert ("process", "Load Sales", "updates_cube", "cube", "Expense") in after_edges
    assert ("process", "Load Sales", "updates_cube", "cube", "Sales") not in after_edges
    # Everything not about this process is untouched.
    assert {e for e in before_edges if e[1] != "Load Sales" and e[4] != "Load Sales"} == {
        e for e in after_edges if e[1] != "Load Sales" and e[4] != "Load Sales"
    }


@pytest.mark.asyncio
async def test_a_deleted_process_leaves_the_map_with_its_links(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")

    await extractor.refresh_process(db_session, connection.id, org.id, "Load Sales", deleted=True)

    objects, edges = await graph_keys(db_session, connection.id)
    assert ("process", "Load Sales") not in objects
    assert not any("Load Sales" in (e[1], e[4]) for e in edges)


@pytest.mark.asyncio
async def test_refresh_is_a_no_op_before_the_first_extraction(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    assert await extractor.refresh_process(db_session, connection.id, org.id, "Load Sales") is False
    count = (await db_session.execute(
        select(TM1Object).where(TM1Object.connection_id == connection.id)
    )).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_processes_link_to_the_views_and_subsets_they_use(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    fake_tm1_client.views.get_all_names.side_effect = lambda cube_name=None, **_: (
        (["Load View"], []) if cube_name == "Expense" else ([], [])
    )
    fake_tm1_client.subsets.get_all_names.side_effect = lambda dimension_name=None, **_: (
        ["Leaves"] if dimension_name == "Region" else []
    )
    process = _make_process(
        "Load Sales",
        datasource_type="TM1CubeView",
        datasource_name="Expense",
        data_code="CellPutN(1, 'Sales', 'NA');",
    )
    process.datasource_view = "Load View"
    process.prolog_procedure = "SubsetElementInsert('Region', 'Leaves', 'NA', 1);"
    fake_tm1_client.processes.get.return_value = process

    await run_extraction(db_session, connection.id, org.id, trigger="manual")
    _, edges = await graph_keys(db_session, connection.id)

    assert ("process", "Load Sales", "reads_view", "view", "Expense:Load View") in edges
    assert ("process", "Load Sales", "uses_subset", "subset", "Region:Leaves") in edges


@pytest.mark.asyncio
async def test_the_agent_can_ask_what_changed(db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")

    result = json.loads(
        await GetModelChangesTool().execute(
            db_session, organization_id=org.id, user_id=admin.id, connection_id=str(connection.id)
        )
    )

    assert len(result["extractions"]) == 1
    assert result["extractions"][0]["status"] == "succeeded"
    assert result["graph"]["extracted_at"]


@pytest.mark.asyncio
async def test_an_approved_process_change_keeps_the_map_in_step(
    db_session, tm1_credentials_key, fake_tm1_client
):
    from src.tm1.deployment.change_service import change_service

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")

    from TM1py import Process

    fake_tm1_client.processes.get.return_value = Process(
        name="Load Sales", data_procedure="CellPutN(1, 'Sales', 'NA');"
    )
    fake_tm1_client.processes.exists.return_value = True
    fake_tm1_client.processes.compile_process.return_value = []
    fake_tm1_client.processes.compile.return_value = []
    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="update_process",
        target_name="Load Sales",
        new_content={"data": "CellPutN(1, 'Expense', 'NA');"},
    )
    # The server returns the saved version once the change is applied.
    def saved(process, *args, **kwargs):
        fake_tm1_client.processes.get.return_value = Process(
            name="Load Sales", data_procedure="CellPutN(1, 'Expense', 'NA');"
        )

    fake_tm1_client.processes.update_or_create.side_effect = saved

    done = await change_service.execute_change(db_session, change, user.id)

    assert done.status == "executed"
    _, edges = await graph_keys(db_session, connection.id)
    assert ("process", "Load Sales", "updates_cube", "cube", "Expense") in edges


@pytest.mark.asyncio
async def test_the_scheduled_refresh_needs_the_cron_secret(client):
    response = await client.get("/internal/cron/refresh-metadata")

    assert response.status_code == 401
