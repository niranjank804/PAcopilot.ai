"""A new public MDX view as a governed change.

What must hold: a draft creates nothing; the view name must be free and
valid, and the MDX must select from the cube and run, or the draft cannot
be applied; applying re-checks the name, creates a public view and reads
it back, deleting it if TM1 did not keep the approved MDX; rollback
deletes the view only while it is exactly what was created; the
assistant drafts views on DEV and never on PROD.
"""

import json

import pytest
from TM1py.Exceptions import TM1pyRestException
from TM1py.Objects import MDXView

from src.ai.tools.tm1.changes import ProposeViewTool
from src.tm1.deployment.change_service import _mdx_cube_problem, _view_name_problems
from tests.fixtures.factories import auth_headers, create_org_admin
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)
from tests.integration.tm1.test_environments import _connection

MDX = "SELECT {[Region].[North]} ON 0 FROM [Sales] WHERE ([Version].[Budget])"


@pytest.fixture
def views(fake_tm1_client):
    """The server's public views, (cube, name) -> MDX, behind TM1py's calls."""

    store: dict[tuple[str, str], str] = {("Sales", "Existing View"): MDX}

    def exists(cube_name, view_name, private=None, **_):
        assert private is False
        return (cube_name, view_name) in store

    def create(view, private=False, **_):
        assert private is False and isinstance(view, MDXView)
        store[(view.cube, view.name)] = view.mdx

    def get(cube_name, view_name, private=False, **_):
        assert private is False
        return MDXView(cube_name, view_name, store[(cube_name, view_name)])

    def delete(cube_name, view_name, private=False, **_):
        assert private is False
        del store[(cube_name, view_name)]

    fake_tm1_client.views.exists.side_effect = exists
    fake_tm1_client.views.create.side_effect = create
    fake_tm1_client.views.get.side_effect = get
    fake_tm1_client.views.delete.side_effect = delete
    fake_tm1_client.cubes.cells.execute_mdx_cellcount.return_value = 1
    fake_tm1_client.cubes.cells.execute_mdx.return_value = {
        ("[Region].[Region].[North]",): {"Value": 10.0}
    }
    return store


@pytest.fixture
async def setup(client, db_session, tm1_credentials_key, views):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    return {"org_id": org.id, "admin_id": admin.id, "headers": headers, "dev": dev}


async def _draft(client, setup, view_name="PBI1234 - 1 Result", mdx=MDX, cube="Sales"):
    return await client.post(
        f"/tm1/connections/{setup['dev']}/changes",
        json={"change_type": "create_view", "target_name": cube,
              "new_content": {"view_name": view_name, "mdx": mdx}},
        headers=setup["headers"],
    )


async def _act(client, setup, change, action):
    return await client.post(f"/tm1/connections/{setup['dev']}/changes/{change}/{action}",
                             json={"acknowledge_impact": True} if action == "execute" else None,
                             headers=setup["headers"])


@pytest.mark.asyncio
async def test_a_draft_runs_the_mdx_and_creates_nothing(client, setup, views, fake_tm1_client):
    resp = await _draft(client, setup)
    assert resp.status_code == 201, resp.text
    change = resp.json()["data"]

    assert change["status"] == "draft" and not change["validation_errors"]
    assert change["impact"] == []
    checks = {c["name"]: c for c in change["checks"]}
    assert checks["View"]["status"] == "pass" and checks["MDX runs"]["status"] == "pass"
    assert "nothing depends on it yet" in checks["Impact"]["detail"]
    assert "only if it is unchanged" in checks["Snapshot and rollback"]["detail"]
    fake_tm1_client.cubes.cells.execute_mdx_cellcount.assert_called_with(MDX)
    fake_tm1_client.views.create.assert_not_called()

    preview = (await client.get(f"/tm1/connections/{setup['dev']}/changes/{change['id']}",
                                headers=setup["headers"])).json()["data"]["preview"]
    assert preview["current"] is None
    assert preview["proposed"]["mdx"] == MDX


@pytest.mark.asyncio
async def test_an_existing_view_is_never_overwritten(client, setup, views, fake_tm1_client):
    resp = await _draft(client, setup, view_name="Existing View")
    assert resp.status_code == 201, resp.text
    assert "already exists" in " ".join(resp.json()["data"]["validation_errors"])

    refused = await _act(client, setup, resp.json()["data"]["id"], "execute")
    assert refused.status_code == 422
    fake_tm1_client.views.create.assert_not_called()


@pytest.mark.asyncio
async def test_mdx_that_does_not_run_or_reads_another_cube_is_refused(client, setup, fake_tm1_client):
    fake_tm1_client.cubes.cells.execute_mdx_cellcount.side_effect = TM1pyRestException(
        '{"error":{"message":"Syntax error at or near: \'SELEC\'"}}', 400, "Bad Request", {}
    )
    broken = (await _draft(client, setup, mdx="SELEC {} ON 0 FROM [Sales]")).json()["data"]
    assert "could not run the MDX" in " ".join(broken["validation_errors"])
    assert {c["name"]: c["status"] for c in broken["checks"]}["MDX runs"] == "fail"
    assert (await _act(client, setup, broken["id"], "execute")).status_code == 422
    await _act(client, setup, broken["id"], "reject")

    elsewhere = (await _draft(
        client, setup, view_name="Other", mdx="SELECT {} ON 0 FROM [Rates]"
    )).json()["data"]
    assert "not from 'Sales'" in " ".join(elsewhere["validation_errors"])
    await _act(client, setup, elsewhere["id"], "reject")

    bad_name = (await _draft(client, setup, view_name="a/b")).json()["data"]
    assert "does not allow" in " ".join(bad_name["validation_errors"])
    fake_tm1_client.views.create.assert_not_called()


@pytest.mark.asyncio
async def test_applying_creates_the_public_view_and_reads_it_back(client, setup, views):
    change = (await _draft(client, setup)).json()["data"]["id"]

    applied = await _act(client, setup, change, "execute")
    assert applied.status_code == 200, applied.text
    data = applied.json()["data"]
    assert data["status"] == "executed"
    assert data["execution_result"] == {"view": "PBI1234 - 1 Result", "cube": "Sales", "private": False}
    assert views[("Sales", "PBI1234 - 1 Result")] == MDX


@pytest.mark.asyncio
async def test_a_view_made_after_the_draft_refuses_the_apply(client, setup, views, fake_tm1_client):
    change = (await _draft(client, setup)).json()["data"]["id"]
    views[("Sales", "PBI1234 - 1 Result")] = "someone else's MDX"

    refused = await _act(client, setup, change, "execute")
    assert refused.status_code == 409
    assert views[("Sales", "PBI1234 - 1 Result")] == "someone else's MDX"
    fake_tm1_client.views.create.assert_not_called()


@pytest.mark.asyncio
async def test_a_view_that_does_not_hold_the_mdx_is_deleted(client, setup, views, fake_tm1_client):
    change = (await _draft(client, setup)).json()["data"]["id"]

    def create_wrong(view, private=False, **_):
        views[(view.cube, view.name)] = "SELECT {} ON 0 FROM [Sales]"

    fake_tm1_client.views.create.side_effect = create_wrong
    result = await _act(client, setup, change, "execute")

    assert result.status_code == 200, result.text
    assert result.json()["data"]["status"] == "failed"
    assert "deleted" in result.json()["data"]["error_message"]
    assert ("Sales", "PBI1234 - 1 Result") not in views


@pytest.mark.asyncio
async def test_rollback_deletes_the_view_it_created(client, setup, views):
    change = (await _draft(client, setup)).json()["data"]["id"]
    await _act(client, setup, change, "execute")

    rolled = await _act(client, setup, change, "rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["data"]["status"] == "rolled_back"
    assert ("Sales", "PBI1234 - 1 Result") not in views
    assert ("Sales", "Existing View") in views


@pytest.mark.asyncio
async def test_rollback_refuses_a_view_changed_since(client, setup, views, fake_tm1_client):
    change = (await _draft(client, setup)).json()["data"]["id"]
    await _act(client, setup, change, "execute")
    edited = "SELECT {[Region].[South]} ON 0 FROM [Sales]"
    views[("Sales", "PBI1234 - 1 Result")] = edited

    refused = await _act(client, setup, change, "rollback")
    assert refused.status_code == 409
    assert "edited since" in refused.json()["error"]["message"]
    assert views[("Sales", "PBI1234 - 1 Result")] == edited
    fake_tm1_client.views.delete.assert_not_called()


@pytest.mark.asyncio
async def test_a_second_view_on_the_same_cube_does_not_replace_an_open_draft(client, setup):
    # A PBI's numbered evidence views ("- 1", "- 2") can be open together.
    first = (await _draft(client, setup)).json()["data"]["id"]
    again = await _draft(client, setup, view_name="PBI1234 - 2 Result")
    assert again.status_code == 201, again.text
    assert again.json()["data"]["id"] != first

    still = (await client.get(f"/tm1/connections/{setup['dev']}/changes/{first}",
                              headers=setup["headers"])).json()["data"]["change"]
    assert still["status"] == "draft"

    # Drafting the same view again replaces the open draft, as for any change.
    replaced = await _draft(client, setup, mdx=MDX + " ")
    assert replaced.status_code == 201, replaced.text


@pytest.mark.asyncio
async def test_the_assistant_drafts_on_dev_and_never_on_prod(client, db_session, setup, fake_tm1_client):
    prod = await _connection(client, setup["headers"], "prod")
    db_session.info.pop("organization_id", None)
    tool = ProposeViewTool()
    args = {"cube_name": "Sales", "view_name": "PBI1234 - 1 Result", "mdx": MDX,
            "rationale": "Evidence for PBI1234"}

    drafted = json.loads(await tool.execute(
        db_session, organization_id=setup["org_id"], user_id=setup["admin_id"],
        connection_id=setup["dev"], **args,
    ))
    assert drafted["status"] == "draft" and "DRAFT" in drafted["note"]
    assert drafted["validation_errors"] == []
    fake_tm1_client.views.create.assert_not_called()

    with pytest.raises(Exception) as refused:
        await tool.execute(
            db_session, organization_id=setup["org_id"], user_id=setup["admin_id"],
            connection_id=prod, **args,
        )
    assert "read-only" in str(refused.value)


def test_view_names_and_mdx_cubes_are_checked_as_tm1_would():
    assert _view_name_problems("PBI1234 - 1 Result") == []
    assert _view_name_problems("   ")
    assert _view_name_problems("x" * 101)
    assert _view_name_problems("a:b") and _view_name_problems("}Hidden")

    # Case and spaces do not matter in TM1 names; "]]" is an escaped "]".
    assert _mdx_cube_problem("select {} on 0 from [s a l e s]", "Sales") is None
    assert _mdx_cube_problem("SELECT {} ON 0 FROM [A]]B]", "A]B") is None
    assert _mdx_cube_problem("SELECT {} ON 0 FROM Sales", "Sales") is None
    # A member named "... From X" is not a FROM clause.
    assert _mdx_cube_problem(
        "SELECT {[Account].[Transfer From Bank]} ON 0 FROM [Sales]", "Sales"
    ) is None
    # Every level of a sub-select must read the target cube.
    assert _mdx_cube_problem(
        "SELECT {} ON 0 FROM (SELECT {} ON 0 FROM [Rates])", "Sales"
    )
    assert _mdx_cube_problem("SELECT {} ON 0", "Sales")
