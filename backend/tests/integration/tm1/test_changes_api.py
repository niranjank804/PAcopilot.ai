from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.models.audit_log import AuditLog
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

    cube = MagicMock()
    cube.name = "Sales"
    cube.dimensions = ["Region"]
    cube.has_rules = True
    cube.rules.text = "['A'] = N: 1;"
    client.cubes.get.return_value = cube
    client.cubes.check_rules.return_value = []

    client.processes.exists.return_value = False
    client.processes.compile_process.return_value = []
    client.processes.compile.return_value = []

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
            "password": "secret",
        },
        headers=headers,
    )
    return resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_change_lifecycle_end_to_end(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = await _create_connection(client, headers)

    create_resp = await client.post(
        f"/tm1/connections/{connection_id}/changes",
        json={
            "change_type": "update_rules",
            "target_name": "Sales",
            "new_content": {"rules": "['A'] = N: 2;"},
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    change = create_resp.json()["data"]
    assert change["status"] == "draft"

    detail_resp = await client.get(
        f"/tm1/connections/{connection_id}/changes/{change['id']}",
        headers=headers,
    )
    assert detail_resp.status_code == 200
    preview = detail_resp.json()["data"]["preview"]
    assert preview["current"] == {"rules": "['A'] = N: 1;"}
    assert preview["proposed"] == {"rules": "['A'] = N: 2;"}

    execute_resp = await client.post(
        f"/tm1/connections/{connection_id}/changes/{change['id']}/execute",
        headers=headers,
    )
    assert execute_resp.status_code == 200
    assert execute_resp.json()["data"]["status"] == "executed"

    rollback_resp = await client.post(
        f"/tm1/connections/{connection_id}/changes/{change['id']}/rollback",
        headers=headers,
    )
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["data"]["status"] == "rolled_back"

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action.in_(
                ["create_change", "execute_change", "rollback_change"]
            )
        )
    )
    actions = {log.action for log in audit_result.scalars().all()}
    assert actions == {"create_change", "execute_change", "rollback_change"}


@pytest.mark.asyncio
async def test_execute_requires_tm1_deploy_permission(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    connection_id = await _create_connection(client, headers)

    create_resp = await client.post(
        f"/tm1/connections/{connection_id}/changes",
        json={
            "change_type": "update_rules",
            "target_name": "Sales",
            "new_content": {"rules": "['A'] = N: 2;"},
        },
        headers=headers,
    )
    change_id = create_resp.json()["data"]["id"]

    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")
    analyst_headers = auth_headers(analyst)

    resp = await client.post(
        f"/tm1/connections/{connection_id}/changes/{change_id}/execute",
        headers=analyst_headers,
    )
    assert resp.status_code == 403
