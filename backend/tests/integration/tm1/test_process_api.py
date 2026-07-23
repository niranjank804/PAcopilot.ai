from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()
    client.processes.get_all_names.return_value = ["Load Sales"]

    process = MagicMock()
    process.name = "Load Sales"
    process.datasource_type = "TM1CubeView"
    process.datasource_data_source_name_for_server = "Sales"
    process.datasource_view = "All Sales"
    process.has_security_access = False
    process.parameters = [{"Name": "pYear", "Prompt": "", "Value": "", "Type": 2}]
    process.prolog_procedure = "# prolog"
    process.metadata_procedure = ""
    process.data_procedure = "CellPutN(1, 'Sales', 'NA');"
    process.epilog_procedure = ""
    client.processes.get.return_value = process

    cube = MagicMock()
    cube.name = "Sales"
    cube.dimensions = ["Region"]
    cube.has_rules = True
    cube.rules.text = "['Total'] = N: DB('Expense', !Region);"
    client.cubes.get.return_value = cube

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
async def test_list_and_get_process_end_to_end(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    list_resp = await client.get(
        f"/tm1/connections/{connection_id}/processes", headers=headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == ["Load Sales"]

    get_resp = await client.get(
        f"/tm1/connections/{connection_id}/processes/Load Sales", headers=headers
    )
    assert get_resp.status_code == 200
    body = get_resp.json()["data"]
    assert body["name"] == "Load Sales"
    assert body["datasource_type"] == "TM1CubeView"
    assert body["datasource_name"] == "Sales"
    assert body["datasource_view"] == "All Sales"
    assert body["parameter_names"] == ["pYear"]
    assert body["prolog"] == "# prolog"
    assert body["data"] == "CellPutN(1, 'Sales', 'NA');"


@pytest.mark.asyncio
async def test_get_cube_rules_end_to_end(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    resp = await client.get(
        f"/tm1/connections/{connection_id}/cubes/Sales/rules", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["name"] == "Sales"
    assert body["rules"] == "['Total'] = N: DB('Expense', !Region);"


@pytest.mark.asyncio
async def test_process_endpoints_require_tm1_read(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")
    viewer_headers = auth_headers(viewer)

    resp = await client.get(
        f"/tm1/connections/{connection_id}/processes", headers=viewer_headers
    )
    assert resp.status_code == 403
