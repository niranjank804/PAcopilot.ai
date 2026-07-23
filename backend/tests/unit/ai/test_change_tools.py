import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.changes import ProposeProcessUpdateTool, ProposeRuleUpdateTool
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import (
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

    cube = MagicMock()
    cube.name = "Sales"
    cube.dimensions = ["Region"]
    cube.has_rules = True
    cube.rules.text = "['A'] = N: 1;"
    client.cubes.get.return_value = cube

    client.processes.exists.return_value = False
    client.processes.compile_process.return_value = []

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


async def _create_connection(db_session, organization_id, created_by):
    return await tm1_integration_service.create_connection(
        db_session,
        organization_id=organization_id,
        created_by=created_by,
        name="Prod",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )


@pytest.mark.asyncio
async def test_propose_rule_update_creates_draft_only(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ProposeRuleUpdateTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        cube_name="Sales",
        rules="['A'] = N: 2;",
    )

    body = json.loads(result)
    assert body["status"] == "draft"
    assert "DRAFT" in body["note"]
    assert "human administrator" in body["note"]
    # Nothing was applied to the server.
    fake_tm1_client.cubes.update_or_create_rules.assert_not_called()


@pytest.mark.asyncio
async def test_propose_process_update_compile_validates(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ProposeProcessUpdateTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        process_name="zProposed",
        create_new=True,
        prolog="# proposed",
    )

    body = json.loads(result)
    assert body["status"] == "draft"
    fake_tm1_client.processes.compile_process.assert_called_once()
    fake_tm1_client.processes.update_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_propose_tools_require_tm1_write(db_session):
    org = await create_organization(db_session)
    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")

    with pytest.raises(PermissionDeniedException):
        await ProposeRuleUpdateTool().execute(
            db_session,
            organization_id=org.id,
            user_id=analyst.id,
            connection_id=str(uuid.uuid4()),
            cube_name="Sales",
            rules="x",
        )
