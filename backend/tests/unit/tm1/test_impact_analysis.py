"""Impact analysis (phase 4): what a change reaches, and how badly.

The model, from tests/unit/tm1/test_extractor.py:
  cubes Sales (Region, Product; rules read Expense) and Expense (Region, Account)
  process Load Sales: reads Expense (cube-view datasource), writes Sales
  chore Load Sales Nightly runs Load Sales
"""

import json

import pytest

from src.ai.tools.tm1.analysis import AnalyzeChangeImpactTool
from src.core.exceptions import ValidationException
from src.tm1.impact.analyzer import analyze_impact, needs_acknowledgement
from src.tm1.metadata.history import run_extraction
from tests.fixtures.factories import auth_headers, create_org_admin, create_organization, create_user
from tests.unit.tm1.test_extractor import (  # noqa: F401 - fixtures
    _create_connection,
    fake_tm1_client,
    tm1_credentials_key,
)


async def _mapped(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")
    return org, user, connection


def _by_name(result):
    return {(i["object_type"], i["name"]): i for i in result["items"]}


@pytest.mark.asyncio
async def test_deleting_a_dimension_is_critical_for_the_cubes_built_on_it(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, _, connection = await _mapped(db_session)

    result = await analyze_impact(db_session, connection.id, org.id, "dimension", "Region", change_kind="delete")
    items = _by_name(result)

    assert items[("cube", "Sales")]["severity"] == "critical"
    assert items[("cube", "Expense")]["severity"] == "critical"
    assert "built on it" in items[("cube", "Sales")]["reason"]
    # Further away is less severe: the load that reads and writes those cubes,
    # and the chore that runs it.
    assert items[("process", "Load Sales")]["depth"] == 2
    assert items[("process", "Load Sales")]["severity"] in ("high", "medium")
    assert items[("chore", "Load Sales Nightly")]["severity"] in ("medium", "low")
    assert result["summary"]["critical"] == 2
    assert sum(result["summary"].values()) == len(result["items"])


@pytest.mark.asyncio
async def test_modifying_is_less_severe_than_deleting(db_session, tm1_credentials_key, fake_tm1_client):
    org, _, connection = await _mapped(db_session)

    modify = await analyze_impact(db_session, connection.id, org.id, "dimension", "Region", change_kind="modify")
    delete = await analyze_impact(db_session, connection.id, org.id, "dimension", "Region", change_kind="delete")

    assert modify["summary"]["critical"] == 0
    assert delete["summary"]["critical"] > 0


@pytest.mark.asyncio
async def test_a_process_change_reaches_its_chore_and_the_data_it_writes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, _, connection = await _mapped(db_session)

    modify = _by_name(await analyze_impact(db_session, connection.id, org.id, "process", "Load Sales"))
    delete = _by_name(await analyze_impact(
        db_session, connection.id, org.id, "process", "Load Sales", change_kind="delete"
    ))

    assert modify[("chore", "Load Sales Nightly")]["severity"] == "medium"
    assert "written by this process" in modify[("cube", "Sales")]["reason"]
    # Deleting what a chore runs breaks the chore outright.
    assert delete[("chore", "Load Sales Nightly")]["severity"] == "critical"
    assert "no longer be maintained" in delete[("cube", "Sales")]["reason"]


@pytest.mark.asyncio
async def test_a_rules_change_flags_the_cube_and_the_rules_that_read_it(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, _, connection = await _mapped(db_session)

    items = _by_name(await analyze_impact(
        db_session, connection.id, org.id, "cube", "Expense", rules_change=True
    ))

    assert items[("cube", "Expense")]["severity"] == "high"
    # Sales's rules read Expense: their results change with it.
    assert items[("cube", "Sales")]["severity"] == "high"


@pytest.mark.asyncio
async def test_an_object_outside_the_map_says_nothing_is_known(db_session, tm1_credentials_key, fake_tm1_client):
    org, _, connection = await _mapped(db_session)

    result = await analyze_impact(db_session, connection.id, org.id, "dimension", "Nowhere")

    assert result["in_graph"] is False and result["items"] == []
    assert "not in the dependency map" in result["not_covered"][0]


@pytest.mark.asyncio
async def test_what_the_map_cannot_see_is_always_listed(db_session, tm1_credentials_key, fake_tm1_client):
    org, _, connection = await _mapped(db_session)

    result = await analyze_impact(db_session, connection.id, org.id, "cube", "Sales")

    assert any("security" in n.lower() for n in result["not_covered"])
    assert result["graph"]["extracted_at"]


def test_only_critical_or_high_impact_needs_confirming():
    assert needs_acknowledgement([{"severity": "critical"}])
    assert needs_acknowledgement([{"severity": "low"}, {"severity": "high"}])
    assert not needs_acknowledgement([{"severity": "medium"}, {"note": "x"}])
    assert not needs_acknowledgement(None)
    # A run's plan carries no severity.
    assert not needs_acknowledgement([{"kind": "parameter", "name": "pYear"}])


@pytest.mark.asyncio
async def test_a_serious_change_is_applied_only_once_its_impact_is_confirmed(
    db_session, tm1_credentials_key, fake_tm1_client
):
    from TM1py import Process

    from src.tm1.deployment.change_service import change_service

    org, user, connection = await _mapped(db_session)
    fake_tm1_client.processes.get.return_value = Process(
        name="Load Sales", data_procedure="CellPutN(1, 'Sales', 'NA');"
    )
    fake_tm1_client.processes.exists.return_value = True

    draft = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="delete_process",
        target_name="Load Sales",
        new_content=None,
    )
    assert needs_acknowledgement(draft.impact)

    with pytest.raises(ValidationException, match="confirm"):
        await change_service.execute_change(db_session, draft, user.id)
    fake_tm1_client.processes.delete.assert_not_called()

    done = await change_service.execute_change(db_session, draft, user.id, acknowledge_impact=True)
    assert done.status == "executed"


@pytest.mark.asyncio
async def test_the_agent_and_the_page_get_the_same_ranked_answer(
    db_session, tm1_credentials_key, fake_tm1_client, client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await run_extraction(db_session, connection.id, org.id, trigger="manual")

    from_tool = json.loads(
        await AnalyzeChangeImpactTool().execute(
            db_session, organization_id=org.id, user_id=admin.id,
            connection_id=str(connection.id), object_type="dimension", name="Region",
            change_kind="delete",
        )
    )
    response = await client.get(
        f"/tm1/connections/{connection.id}/metadata/impact",
        params={"object_type": "dimension", "name": "Region", "change_kind": "delete"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"] == from_tool["summary"]
    assert from_tool["summary"]["critical"] == 2
