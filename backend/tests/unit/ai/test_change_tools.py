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


# --- Exact copies ----------------------------------------------------------
#
# Asked for "a copy of IT_Load Data", the Administrator agent refused and
# the agents that could draft would have retyped the process by hand. The
# copy tool reads the original from the server instead.


def _source_process():
    from TM1py import Process

    process = Process(
        name="IT_Load Data",
        datasource_type="ASCII",
        datasource_data_source_name_for_server="Project.csv",
        datasource_ascii_delimiter_char=";",
        datasource_ascii_quote_character="'",
        datasource_ascii_header_records=1,
        data_procedure="if(Customer @<> 'NaOrg'); ItemSkip; EndIf;\r\nCellPutN(nValue, 'IT_Project', Customer);",
    )
    process.add_variable("Customer", "String")
    process.add_variable("nValue", "Numeric")
    process.add_parameter("pYear", "Year", "2026", parameter_type="String")
    return process


@pytest.mark.asyncio
async def test_propose_process_copy_drafts_an_exact_copy_without_writing(
    db_session, tm1_credentials_key, fake_tm1_client
):
    from src.ai.tools.tm1.changes import ProposeProcessCopyTool
    from src.tm1.deployment.change_service import _build_process

    fake_tm1_client.processes.get.return_value = _source_process()

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    result = json.loads(
        await ProposeProcessCopyTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            source_process="IT_Load Data",
            new_process_name="IT_Load Data - Copy",
        )
    )

    assert result["status"] == "draft"
    assert result["copied_from"] == "IT_Load Data"
    assert result["copy_summary"]["datasource_type"] == "ASCII"
    assert result["copy_summary"]["datasource_name"] == "Project.csv"
    assert result["copy_summary"]["parameters"] == ["pYear"]
    assert result["copy_summary"]["variables"] == ["Customer", "nValue"]
    # A draft only: nothing created on the server.
    fake_tm1_client.processes.update_or_create.assert_not_called()

    from sqlalchemy import select

    from src.database.models.tm1_change import TM1Change

    change = (
        await db_session.execute(
            select(TM1Change).where(TM1Change.id == uuid.UUID(result["draft_change_id"]))
        )
    ).scalar_one()

    assert change.change_type == "create_process"
    assert change.target_name == "IT_Load Data - Copy"
    assert change.validation_errors is None

    # What would be deployed is the original, renamed — including the
    # settings the ordinary draft format has no field for.
    built = _build_process(change.target_name, change.new_content)
    original = _source_process()

    assert built.name == "IT_Load Data - Copy"
    assert built.data_procedure == original.data_procedure
    assert built.datasource_ascii_delimiter_char == ";"
    assert built.datasource_ascii_quote_character == "'"
    assert built.datasource_ascii_header_records == 1
    assert [v["Name"] for v in built.variables] == ["Customer", "nValue"]
    assert [p["Name"] for p in built.parameters] == ["pYear"]


@pytest.mark.asyncio
async def test_propose_process_copy_refuses_to_copy_onto_itself(
    db_session, tm1_credentials_key, fake_tm1_client
):
    from src.ai.tools.tm1.changes import ProposeProcessCopyTool
    from src.core.exceptions import ValidationException

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    with pytest.raises(ValidationException):
        await ProposeProcessCopyTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            source_process="IT_Load Data",
            # TM1 names are case-insensitive: this is the same process.
            new_process_name="it_load data",
        )


@pytest.mark.asyncio
async def test_propose_process_copy_requires_tm1_write(db_session):
    from src.ai.tools.tm1.changes import ProposeProcessCopyTool

    org = await create_organization(db_session)
    analyst = await create_user(db_session, org.id)
    await grant_system_role(db_session, analyst.id, "Analyst")

    with pytest.raises(PermissionDeniedException):
        await ProposeProcessCopyTool().execute(
            db_session,
            organization_id=org.id,
            user_id=analyst.id,
            connection_id=str(uuid.uuid4()),
            source_process="IT_Load Data",
            new_process_name="Copy",
        )


def test_copying_is_offered_by_the_agents_asked_to_copy():
    from src.ai.agents.registry import get_agent

    for name in ("administrator", "ti", "developer"):
        assert "propose_process_copy" in get_agent(name).tool_names
