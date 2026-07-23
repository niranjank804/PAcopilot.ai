import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.chores import GetChoreTool, ListChoresTool
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
    client.chores.get_all_names.return_value = ["Load Sales Nightly"]

    task = MagicMock()
    task.process_name = "Load Sales"

    chore = MagicMock()
    chore.name = "Load Sales Nightly"
    chore.active = True
    chore.tasks = [task]
    client.chores.get.return_value = chore

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
async def test_list_chores_tool_returns_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ListChoresTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
    )

    assert json.loads(result) == {"chores": ["Load Sales Nightly"]}


@pytest.mark.asyncio
async def test_get_chore_tool_returns_details(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await GetChoreTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        chore_name="Load Sales Nightly",
    )

    assert json.loads(result) == {
        "name": "Load Sales Nightly",
        "active": True,
        "process_names": ["Load Sales"],
    }


@pytest.mark.asyncio
async def test_chore_tools_raise_when_lacking_permission(db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await ListChoresTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
        )

    with pytest.raises(PermissionDeniedException):
        await GetChoreTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
            chore_name="Load Sales Nightly",
        )
