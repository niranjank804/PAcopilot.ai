from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_organization,
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
    client.cubes.get_all_names.return_value = ["Sales"]

    fake_cube = MagicMock()
    fake_cube.name = "Sales"
    fake_cube.dimensions = ["Region"]
    fake_cube.has_rules = True
    client.cubes.get.return_value = fake_cube

    client.dimensions.get_all_names.return_value = ["Region"]

    fake_dimension = MagicMock()
    fake_dimension.name = "Region"
    fake_dimension.hierarchy_names = ["Region"]
    client.dimensions.get.return_value = fake_dimension

    client.server.get_server_name.return_value = "TM1_SERVER"

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


async def _create_connection(client, headers):
    resp = await client.post(
        "/tm1/connections",
        json={
            "name": "Prod",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "super-secret",
        },
        headers=headers,
    )
    return resp


@pytest.mark.asyncio
async def test_create_connection_hides_password(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    resp = await _create_connection(client, headers)

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "password" not in body
    assert "encrypted_password" not in body


@pytest.mark.asyncio
async def test_connection_write_requires_permission(
    client, db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    resp = await _create_connection(client, auth_headers(viewer))

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_read_tm1_connections(client, db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    resp = await client.get("/tm1/connections", headers=auth_headers(viewer))

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_org_connection_access_is_404(client, db_session, tm1_credentials_key):
    org_a, admin_a = await create_org_admin(db_session)
    org_b, admin_b = await create_org_admin(db_session)
    headers_a = auth_headers(admin_a)
    headers_b = auth_headers(admin_b)

    create_resp = await _create_connection(client, headers_a)
    connection_id = create_resp.json()["data"]["id"]

    get_resp = await client.get(f"/tm1/connections/{connection_id}", headers=headers_b)
    assert get_resp.status_code == 404

    delete_resp = await client.delete(
        f"/tm1/connections/{connection_id}", headers=headers_b
    )
    assert delete_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_cubes_and_get_cube(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    list_resp = await client.get(
        f"/tm1/connections/{connection_id}/cubes", headers=headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == ["Sales"]

    get_resp = await client.get(
        f"/tm1/connections/{connection_id}/cubes/Sales", headers=headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["has_rules"] is True


@pytest.mark.asyncio
async def test_test_connection_endpoint(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    resp = await client.post(
        f"/tm1/connections/{connection_id}/test", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is True


@pytest.mark.asyncio
async def test_delete_connection(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    delete_resp = await client.delete(
        f"/tm1/connections/{connection_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    get_resp = await client.get(f"/tm1/connections/{connection_id}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_update_connection_name_and_address(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    update_resp = await client.patch(
        f"/tm1/connections/{connection_id}",
        json={"name": "Prod (renamed)", "address": "tm1-new.example.com"},
        headers=headers,
    )

    assert update_resp.status_code == 200
    body = update_resp.json()["data"]
    assert body["name"] == "Prod (renamed)"
    assert body["address"] == "tm1-new.example.com"
    assert body["port"] == 8010
    assert "password" not in body


@pytest.mark.asyncio
async def test_update_connection_password_is_reencrypted(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    update_resp = await client.patch(
        f"/tm1/connections/{connection_id}",
        json={"password": "new-secret"},
        headers=headers,
    )

    assert update_resp.status_code == 200

    from src.database.models.tm1_connection import TM1Connection
    from src.tm1.crypto import decrypt_password

    connection = await db_session.get(TM1Connection, connection_id)
    assert decrypt_password(connection.encrypted_password) == "new-secret"


@pytest.mark.asyncio
async def test_update_connection_to_v12_saas_requires_tenant_and_database(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    update_resp = await client.patch(
        f"/tm1/connections/{connection_id}",
        json={"authentication_type": "v12_saas"},
        headers=headers,
    )

    assert update_resp.status_code == 422


@pytest.mark.asyncio
async def test_update_connection_requires_write_permission(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    update_resp = await client.patch(
        f"/tm1/connections/{connection_id}",
        json={"name": "Hijacked"},
        headers=auth_headers(viewer),
    )

    assert update_resp.status_code == 403


@pytest.mark.asyncio
async def test_update_connection_cross_org_is_404(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    create_resp = await _create_connection(client, auth_headers(admin))
    connection_id = create_resp.json()["data"]["id"]

    other_org, other_admin = await create_org_admin(db_session)

    update_resp = await client.patch(
        f"/tm1/connections/{connection_id}",
        json={"name": "Hijacked"},
        headers=auth_headers(other_admin),
    )

    assert update_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_cubes_writes_structured_audit_log(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    from sqlalchemy import select

    from src.database.models.audit_log import AuditLog

    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    await client.get(f"/tm1/connections/{connection_id}/cubes", headers=headers)

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "TM1Connection",
            AuditLog.action == "list_cubes",
        )
    )
    logs = [
        log for log in result.scalars().all() if str(log.entity_id) == connection_id
    ]

    assert len(logs) == 1
    assert "correlation_id" in logs[0].new_values
    assert "elapsed_ms" in logs[0].new_values
    assert logs[0].new_values["rows_returned"] == 1
    assert logs[0].new_values["server"] == "tm1.example.com"
