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
    client.security.get_all_groups.return_value = ["ADMIN", "Planners"]
    client.security.get_user_names_from_group.return_value = ["alice", "bob"]

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
async def test_org_admin_can_list_and_get_security_groups(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    list_resp = await client.get(
        f"/tm1/connections/{connection_id}/security/groups", headers=headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["data"] == ["ADMIN", "Planners"]

    get_resp = await client.get(
        f"/tm1/connections/{connection_id}/security/groups/Planners",
        headers=headers,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"] == {
        "name": "Planners",
        "member_user_names": ["alice", "bob"],
    }


@pytest.mark.asyncio
async def test_plain_tm1_read_cannot_list_security_groups(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    # Analyst has tm1.read (per scripts/seed_permissions.py) but not the
    # narrower tm1.security.read.
    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")
    analyst_headers = auth_headers(analyst)

    resp = await client.get(
        f"/tm1/connections/{connection_id}/security/groups",
        headers=analyst_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_plain_tm1_read_cannot_get_security_group(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)

    create_resp = await _create_connection(client, headers)
    connection_id = create_resp.json()["data"]["id"]

    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")
    analyst_headers = auth_headers(analyst)

    resp = await client.get(
        f"/tm1/connections/{connection_id}/security/groups/Planners",
        headers=analyst_headers,
    )
    assert resp.status_code == 403
