import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.base import CODE_TRUNCATION_LIMIT
from src.ai.tools.tm1.cubes import GetCubeRulesTool
from src.ai.tools.tm1.metadata import GetObjectRelationshipsTool
from src.ai.tools.tm1.processes import GetProcessTool, ListProcessesTool
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
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
    client.processes.get_all_names.return_value = ["Load Sales"]

    process = MagicMock()
    process.name = "Load Sales"
    process.datasource_type = "TM1CubeView"
    process.datasource_data_source_name_for_server = "Sales"
    process.datasource_view = "All Sales"
    process.has_security_access = False
    process.parameters = [{"Name": "pYear", "Prompt": "", "Value": "", "Type": 2}]
    process.prolog_procedure = "x" * (CODE_TRUNCATION_LIMIT + 100)
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
async def test_list_processes_tool_returns_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await ListProcessesTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
    )

    assert json.loads(result) == {"processes": ["Load Sales"]}


@pytest.mark.asyncio
async def test_get_process_tool_returns_details_and_truncates_long_code(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await GetProcessTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        process_name="Load Sales",
    )

    body = json.loads(result)
    assert body["name"] == "Load Sales"
    assert body["datasource_type"] == "TM1CubeView"
    assert body["datasource_name"] == "Sales"
    assert body["parameter_names"] == ["pYear"]
    assert body["data"] == "CellPutN(1, 'Sales', 'NA');"
    assert body["prolog"].endswith("[truncated]")
    assert len(body["prolog"]) < CODE_TRUNCATION_LIMIT + 100


@pytest.mark.asyncio
async def test_get_cube_rules_tool_returns_rule_text(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = await GetCubeRulesTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        cube_name="Sales",
    )

    assert json.loads(result) == {
        "name": "Sales",
        "rules": "['Total'] = N: DB('Expense', !Region);",
    }


@pytest.mark.asyncio
async def test_get_object_relationships_tool_returns_both_directions(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    now = datetime.now(timezone.utc)

    cube = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection.id,
            organization_id=org.id,
            object_type="cube",
            name="Sales",
            extracted_at=now,
        ),
    )
    process = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection.id,
            organization_id=org.id,
            object_type="process",
            name="Load Sales",
            extracted_at=now,
        ),
    )
    await tm1_relationship_repository.create(
        db_session,
        TM1Relationship(
            connection_id=connection.id,
            organization_id=org.id,
            from_object_id=process.id,
            to_object_id=cube.id,
            relationship_type="updates_cube",
            extracted_at=now,
        ),
    )

    result = await GetObjectRelationshipsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        object_type="cube",
        name="Sales",
    )

    body = json.loads(result)
    assert body["object_type"] == "cube"
    assert body["name"] == "Sales"
    assert body["outgoing"] == []
    assert body["incoming"] == [
        {
            "relationship_type": "updates_cube",
            "object_type": "process",
            "name": "Load Sales",
        }
    ]


@pytest.mark.asyncio
async def test_process_tools_raise_when_lacking_permission(db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await ListProcessesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
        )

    with pytest.raises(PermissionDeniedException):
        await GetObjectRelationshipsTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
            object_type="cube",
            name="Sales",
        )
