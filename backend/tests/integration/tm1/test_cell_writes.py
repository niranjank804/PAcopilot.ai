"""Cell write-back as a governed change.

What must hold: a draft writes nothing; only leaf, non-rule cells of the
right type can be written; the values are saved when applying and the
write is verified, with the old values written back if it does not hold;
a drift since drafting refuses the apply; rollback writes the saved values
back, and refuses over later writes; data is not promoted; the assistant
cannot draft writes on PROD.
"""

import json

import pytest

from src.ai.tools.tm1.changes import ProposeCellWriteTool
from src.tm1.services import cell_service
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection

DIMENSIONS = ["Version", "Region", "Measure"]


@pytest.fixture
def cells(monkeypatch, fake_tm1_client):
    """The cube's cells: values and what TM1 says about each."""

    store = {
        ("Budget", "North", "Rate"): {"value": 1.1},
        ("Budget", "South", "Rate"): {"value": 1.2},
        ("Budget", "Total", "Rate"): {"value": 2.3, "consolidated": True},
        ("Budget", "North", "Amount"): {"value": 500.0, "rule_derived": True},
        ("Budget", "North", "Comment"): {"value": "ok"},
    }

    async def read_cells(client, connection_id, cube, coordinates, **_):
        unknown = [c for c in coordinates if tuple(c) not in store]
        if unknown:
            return {"dimensions": DIMENSIONS,
                    "invalid": [{"dimension": "Region", "element": c[1]} for c in unknown]}
        return {"dimensions": DIMENSIONS, "cells": [
            {"coordinates": dict(zip(DIMENSIONS, c)), "value": store[tuple(c)]["value"],
             "rule_derived": store[tuple(c)].get("rule_derived", False),
             "consolidated": store[tuple(c)].get("consolidated", False), "updateable": 1}
            for c in coordinates
        ]}

    monkeypatch.setattr(cell_service, "read_cells", read_cells)

    def write_values(cube, values, dimensions=None):
        assert dimensions == DIMENSIONS
        for coordinates, value in values.items():
            store[coordinates]["value"] = value

    fake_tm1_client.cells.write_values.side_effect = write_values
    fake_tm1_client.cubes.get.return_value.dimensions = DIMENSIONS
    return store


@pytest.fixture
async def setup(client, db_session, tm1_credentials_key, cells):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    return {"org_id": org.id, "admin_id": admin.id, "headers": headers, "dev": dev}


async def _draft(client, setup, connection, cells_to_write):
    return await client.post(
        f"/tm1/connections/{connection}/changes",
        json={"change_type": "write_cells", "target_name": "Rates",
              "new_content": {"cells": cells_to_write, "reason": "New FX rates"}},
        headers=setup["headers"],
    )


def _cell(region, value, measure="Rate"):
    return {"coordinates": ["Budget", region, measure], "value": value}


async def _act(client, setup, connection, change, action):
    return await client.post(f"/tm1/connections/{connection}/changes/{change}/{action}",
                             json={"acknowledge_impact": True} if action == "execute" else None,
                             headers=setup["headers"])


@pytest.mark.asyncio
async def test_a_draft_shows_current_and_new_values_and_writes_nothing(client, setup, cells, fake_tm1_client):
    resp = await _draft(client, setup, setup["dev"], [_cell("North", 1.5), _cell("South", 1.2)])
    assert resp.status_code == 201, resp.text
    change = resp.json()["data"]
    assert change["status"] == "draft" and not change["validation_errors"]
    assert "2 leaf cell(s), 1 with a new value" in json.dumps(change["checks"])
    fake_tm1_client.cells.write_values.assert_not_called()

    preview = (await client.get(f"/tm1/connections/{setup['dev']}/changes/{change['id']}",
                                headers=setup["headers"])).json()["data"]["preview"]
    assert preview["current"]["cells"][0] == {"coordinates": ["Budget", "North", "Rate"], "value": 1.1}
    assert preview["proposed"]["cells"][0]["value"] == 1.5


@pytest.mark.asyncio
async def test_consolidated_rule_and_mistyped_cells_are_refused(client, setup):
    resp = await _draft(client, setup, setup["dev"], [
        _cell("Total", 9), _cell("North", 9, "Amount"), _cell("North", 3, "Comment"),
        _cell("South", 1), _cell("South", 2),
    ])
    assert resp.status_code == 201, resp.text
    errors = " | ".join(resp.json()["data"]["validation_errors"])
    assert "consolidated" in errors and "calculated by a rule" in errors
    assert "string cell" in errors and "listed more than once" in errors

    refused = await _act(client, setup, setup["dev"], resp.json()["data"]["id"], "execute")
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_unknown_elements_and_oversized_writes_are_refused(client, setup):
    unknown = await _draft(client, setup, setup["dev"], [_cell("Atlantis", 1)])
    assert "do not exist" in " ".join(unknown.json()["data"]["validation_errors"])

    too_many = await _draft(client, setup, setup["dev"], [_cell("North", i) for i in range(201)])
    assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_applying_saves_the_old_values_and_rollback_writes_them_back(client, setup, cells):
    change = (await _draft(client, setup, setup["dev"], [_cell("North", 1.5)])).json()["data"]["id"]

    applied = await _act(client, setup, setup["dev"], change, "execute")
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["status"] == "executed"
    assert cells[("Budget", "North", "Rate")]["value"] == 1.5

    rolled = await _act(client, setup, setup["dev"], change, "rollback")
    assert rolled.status_code == 200, rolled.text
    assert cells[("Budget", "North", "Rate")]["value"] == 1.1


@pytest.mark.asyncio
async def test_a_value_changed_since_the_draft_refuses_the_apply(client, setup, cells):
    change = (await _draft(client, setup, setup["dev"], [_cell("North", 1.5)])).json()["data"]["id"]
    cells[("Budget", "North", "Rate")]["value"] = 1.4  # someone typed in it meanwhile

    refused = await _act(client, setup, setup["dev"], change, "execute")
    assert refused.status_code == 409
    assert cells[("Budget", "North", "Rate")]["value"] == 1.4


@pytest.mark.asyncio
async def test_rollback_refuses_over_a_later_write(client, setup, cells):
    change = (await _draft(client, setup, setup["dev"], [_cell("North", 1.5)])).json()["data"]["id"]
    await _act(client, setup, setup["dev"], change, "execute")
    cells[("Budget", "North", "Rate")]["value"] = 1.6

    refused = await _act(client, setup, setup["dev"], change, "rollback")
    assert refused.status_code == 409
    assert cells[("Budget", "North", "Rate")]["value"] == 1.6


@pytest.mark.asyncio
async def test_a_write_the_server_does_not_hold_is_undone(client, setup, cells, fake_tm1_client):
    change = (await _draft(client, setup, setup["dev"], [_cell("North", 1.5)])).json()["data"]["id"]
    writes = []

    def ignore_first(cube, values, dimensions=None):
        writes.append(dict(values))
        if len(writes) > 1:  # the restore lands
            for coordinates, value in values.items():
                cells[coordinates]["value"] = value

    fake_tm1_client.cells.write_values.side_effect = ignore_first
    result = await _act(client, setup, setup["dev"], change, "execute")

    assert result.status_code == 200, result.text
    assert result.json()["data"]["status"] == "failed"
    assert "written back" in result.json()["data"]["error_message"]
    assert writes[-1] == {("Budget", "North", "Rate"): 1.1}


@pytest.mark.asyncio
async def test_data_is_not_promoted(client, setup):
    change = (await _draft(client, setup, setup["dev"], [_cell("North", 1.5)])).json()["data"]["id"]
    await _act(client, setup, setup["dev"], change, "execute")
    qa = await _connection(client, setup["headers"], "qa")

    promoted = await client.post(f"/tm1/connections/{setup['dev']}/changes/{change}/promote",
                                 json={"target_connection_id": qa}, headers=setup["headers"])
    assert promoted.status_code == 422
    assert "cell write is not promoted" in promoted.json()["error"]["message"]


@pytest.mark.asyncio
async def test_the_assistant_drafts_on_dev_and_never_on_prod(client, db_session, setup, fake_tm1_client):
    prod = await _connection(client, setup["headers"], "prod")
    db_session.info.pop("organization_id", None)
    tool = ProposeCellWriteTool()

    drafted = json.loads(await tool.execute(
        db_session, organization_id=setup["org_id"], user_id=setup["admin_id"],
        connection_id=setup["dev"], cube_name="Rates", cells=[_cell("North", 1.5)], reason="New rate",
    ))
    assert drafted["status"] == "draft" and "DRAFT" in drafted["note"]
    fake_tm1_client.cells.write_values.assert_not_called()

    with pytest.raises(Exception) as refused:
        await tool.execute(
            db_session, organization_id=setup["org_id"], user_id=setup["admin_id"],
            connection_id=prod, cube_name="Rates", cells=[_cell("North", 1.5)], reason="New rate",
        )
    assert "read-only" in str(refused.value)
