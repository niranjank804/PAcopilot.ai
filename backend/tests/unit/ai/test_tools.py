import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.cells import ExecuteMDXTool
from src.ai.tools.tm1.cubes import GetCubeTool, ListCubesTool
from src.ai.tools.tm1.dimensions import (
    GetDimensionTool,
    ListDimensionElementsTool,
    ListDimensionsTool,
)
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
    client.cubes.get_all_names.return_value = ["Sales"]

    fake_cube = MagicMock()
    fake_cube.name = "Sales"
    fake_cube.dimensions = ["Region"]
    fake_cube.has_rules = True
    client.cubes.get.return_value = fake_cube

    client.dimensions.get_all_names.return_value = ["Region"]

    fake_dimension = MagicMock()
    fake_dimension.name = "Region"
    fake_dimension.hierarchy_names = ["Region", "Region Alt"]
    client.dimensions.get.return_value = fake_dimension

    client.elements.get_element_names.return_value = ["North", "South"]
    client.cubes.cells.execute_mdx_elements_value_dict.return_value = {
        "North|Actual": 100.0,
        "South|Actual": 200.0,
    }

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
async def test_list_cubes_tool_returns_cube_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ListCubesTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
    )

    assert json.loads(result) == {"cubes": ["Sales"]}


@pytest.mark.asyncio
async def test_get_cube_tool_returns_cube_details(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await GetCubeTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        cube_name="Sales",
    )

    assert json.loads(result) == {
        "name": "Sales",
        "dimensions": ["Region"],
        "has_rules": True,
    }


@pytest.mark.asyncio
async def test_list_dimensions_tool_returns_dimension_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ListDimensionsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
    )

    assert json.loads(result) == {"dimensions": ["Region"]}


@pytest.mark.asyncio
async def test_get_dimension_tool_returns_dimension_details(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await GetDimensionTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        dimension_name="Region",
    )

    assert json.loads(result) == {
        "name": "Region",
        "hierarchy_names": ["Region", "Region Alt"],
    }


@pytest.mark.asyncio
async def test_list_dimension_elements_tool_returns_element_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ListDimensionElementsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        dimension_name="Region",
    )

    assert json.loads(result) == {
        "dimension_name": "Region",
        "elements": ["North", "South"],
    }


@pytest.mark.asyncio
async def test_execute_mdx_tool_returns_cell_values(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ExecuteMDXTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        mdx="SELECT ... FROM [Sales]",
    )

    assert json.loads(result) == {
        "cells": {"North|Actual": 100.0, "South|Actual": 200.0},
        "cell_count": 2,
    }


@pytest.mark.asyncio
async def test_tool_execute_raises_when_user_lacks_tm1_read_permission(db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await ListCubesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
        )
