from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def _make_cube(name, dimensions):
    cube = MagicMock()
    cube.name = name
    cube.dimensions = dimensions
    cube.has_rules = False
    return cube


def _make_dimension(name, hierarchy_names):
    dimension = MagicMock()
    dimension.name = name
    dimension.hierarchy_names = hierarchy_names
    return dimension


def _make_process(name, datasource_name, data_code):
    process = MagicMock()
    process.name = name
    process.datasource_type = "TM1CubeView"
    process.datasource_data_source_name_for_server = datasource_name
    process.datasource_view = ""
    process.has_security_access = False
    process.parameters = []
    process.prolog_procedure = ""
    process.metadata_procedure = ""
    process.data_procedure = data_code
    process.epilog_procedure = ""
    return process


def _make_chore(name, process_names):
    tasks = []

    for process_name in process_names:
        task = MagicMock()
        task.process_name = process_name
        tasks.append(task)

    chore = MagicMock()
    chore.name = name
    chore.active = True
    chore.tasks = tasks
    return chore


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()
    client.cubes.get_all_names.return_value = ["Sales"]

    cubes_by_name = {"Sales": _make_cube("Sales", ["Region", "Product"])}
    client.cubes.get.side_effect = lambda name: cubes_by_name[name]

    dimensions_by_name = {
        "Region": _make_dimension("Region", ["Region"]),
        "Product": _make_dimension("Product", ["Product"]),
    }
    client.dimensions.get.side_effect = lambda name: dimensions_by_name[name]

    client.processes.get_all_names.return_value = ["Load Sales"]
    client.processes.get.return_value = _make_process(
        "Load Sales", "Sales", "CellPutN(1, 'Sales', 'NA');"
    )

    client.chores.get_all_names.return_value = ["Load Sales Nightly"]
    client.chores.get.return_value = _make_chore(
        "Load Sales Nightly", ["Load Sales"]
    )

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


async def _create_connection(client, headers):
    return await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_extract_and_query_dependencies_end_to_end(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    extract_resp = await client.post(
        f"/tm1/connections/{connection_id}/metadata/extract", headers=headers
    )
    assert extract_resp.status_code == 200
    summary = extract_resp.json()["data"]
    # 1 cube + 2 dimensions + 2 hierarchies + 1 process + 1 chore
    assert summary["objects_created"] == 7
    # 2 uses_dimension + 2 contains_hierarchy + 1 reads_cube + 1 updates_cube
    # + 1 runs_process
    assert summary["relationships_created"] == 7

    deps_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/cubes/Sales/dependencies",
        headers=headers,
    )
    assert deps_resp.status_code == 200
    assert set(deps_resp.json()["data"]) == {"Region", "Product"}

    dependents_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/dimensions/Region/dependents",
        headers=headers,
    )
    assert dependents_resp.status_code == 200
    assert dependents_resp.json()["data"] == ["Sales"]

    relationships_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/objects/cube/Sales/relationships",
        headers=headers,
    )
    assert relationships_resp.status_code == 200
    relationships = relationships_resp.json()["data"]
    assert relationships["object_type"] == "cube"
    assert relationships["name"] == "Sales"
    incoming_types = {
        (r["relationship_type"], r["name"]) for r in relationships["incoming"]
    }
    assert incoming_types == {
        ("reads_cube", "Load Sales"),
        ("updates_cube", "Load Sales"),
    }
    outgoing_types = {
        (r["relationship_type"], r["name"]) for r in relationships["outgoing"]
    }
    assert outgoing_types == {
        ("uses_dimension", "Region"),
        ("uses_dimension", "Product"),
    }

    chore_relationships_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/objects/chore/"
        f"{quote('Load Sales Nightly')}/relationships",
        headers=headers,
    )
    assert chore_relationships_resp.status_code == 200
    chore_relationships = chore_relationships_resp.json()["data"]
    assert chore_relationships["outgoing"] == [
        {
            "relationship_type": "runs_process",
            "object_type": "process",
            "name": "Load Sales",
        }
    ]


@pytest.mark.asyncio
async def test_dependency_traversal_endpoints_end_to_end(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    extract_resp = await client.post(
        f"/tm1/connections/{connection_id}/metadata/extract", headers=headers
    )
    assert extract_resp.status_code == 200

    dependents_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/objects/cube/Sales/dependents",
        headers=headers,
    )
    assert dependents_resp.status_code == 200
    dependents_names = {
        (d["object_type"], d["name"]) for d in dependents_resp.json()["data"]
    }
    assert ("process", "Load Sales") in dependents_names
    assert ("chore", "Load Sales Nightly") in dependents_names

    dependencies_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/objects/process/"
        f"{quote('Load Sales')}/dependencies",
        headers=headers,
    )
    assert dependencies_resp.status_code == 200
    dependencies_names = {
        (d["object_type"], d["name"]) for d in dependencies_resp.json()["data"]
    }
    assert ("cube", "Sales") in dependencies_names
    assert ("dimension", "Region") in dependencies_names
    assert ("dimension", "Product") in dependencies_names

    path_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/path",
        params={
            "from_type": "chore",
            "from_name": "Load Sales Nightly",
            "to_type": "cube",
            "to_name": "Sales",
        },
        headers=headers,
    )
    assert path_resp.status_code == 200
    path_body = path_resp.json()["data"]
    assert path_body["found"] is True
    assert [(p["object_type"], p["name"]) for p in path_body["path"]] == [
        ("chore", "Load Sales Nightly"),
        ("process", "Load Sales"),
        ("cube", "Sales"),
    ]

    unused_resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/unused",
        headers=headers,
    )
    assert unused_resp.status_code == 200
    assert unused_resp.json()["data"] == []


@pytest.mark.asyncio
async def test_metadata_extract_requires_write_permission(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")

    resp = await client.post(
        f"/tm1/connections/{connection_id}/metadata/extract",
        headers=auth_headers(analyst),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_cube_dependencies_before_extraction_is_404(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/tm1/connections/{connection_id}/metadata/cubes/Sales/dependencies",
        headers=headers,
    )
    assert resp.status_code == 404
