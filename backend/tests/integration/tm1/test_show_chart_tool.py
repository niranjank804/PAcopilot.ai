import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.registry import get_tool
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.tm1.client.connection_manager import tm1_connection_manager
from tests.fixtures.factories import auth_headers, create_org_admin, create_user


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
    client.cubes.cells.execute_mdx.return_value = {
        ("[Period].[Period].[Jan-2026]", "[Version].[Version].[Plan]"): {"Value": 125000.0},
        ("[Period].[Period].[Feb-2026]", "[Version].[Version].[Plan]"): {"Value": 131000.0},
    }
    monkeypatch.setattr(
        tm1_connection_manager, "get_client", AsyncMock(return_value=client)
    )
    return client


async def _connection_id(client, admin) -> str:
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
        headers=auth_headers(admin),
    )
    return resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_show_chart_returns_what_the_model_needs_to_explain_it(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection_id = await _connection_id(client, admin)

    result = json.loads(
        await get_tool("show_chart").execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=connection_id,
            mdx="SELECT ... FROM [Income]",
            title="Revenue by month, 2026",
            visual="line",
        )
    )

    assert result["shown"] is True
    assert result["title"] == "Revenue by month, 2026"
    assert result["dimensions"] == ["Period", "Version"]
    assert result["cell_count"] == 2
    assert {"members": {"Period": "Jan-2026", "Version": "Plan"}, "value": 125000.0} in result["rows"]


@pytest.mark.asyncio
async def test_show_chart_says_so_when_the_query_is_empty(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection_id = await _connection_id(client, admin)
    fake_tm1_client.cubes.cells.execute_mdx.return_value = {}

    result = json.loads(
        await get_tool("show_chart").execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=connection_id,
            mdx="SELECT ... FROM [Income]",
            title="Actuals",
        )
    )

    assert result["shown"] is False
    assert "no cells" in result["reason"]


@pytest.mark.asyncio
async def test_show_chart_needs_tm1_read(
    client, db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection_id = await _connection_id(client, admin)
    viewer = await create_user(db_session, org.id)

    with pytest.raises(PermissionDeniedException):
        await get_tool("show_chart").execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=connection_id,
            mdx="SELECT ... FROM [Income]",
            title="Revenue",
        )


def test_the_analyst_can_show_charts():
    from src.ai.agents.registry import get_agent

    assert "show_chart" in get_agent("analyst").tool_names
