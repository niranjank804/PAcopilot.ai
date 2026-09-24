import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.health import RunModelHealthCheckTool
from src.ai.tools.tm1.processes import DiffProcessTool
from src.ai.tools.tm1.structure import (
    GetDimensionAttributesTool,
    GetElementContextTool,
    GetServerStateTool,
    ListCubeViewsTool,
    ListDimensionSubsetsTool,
)
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_org_admin, create_organization, create_user

SERVER_PROLOG = "sYear = '2026';\nnCount = 0;"
BROKEN_RULES = """
SKIPCHECK;
['Margin'] = N: ['Revenue'] - ['Cost'];
FEEDERS;
['Revenue'] => ['Elsewhere'];
"""


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def _attribute(name, kind):
    attr = MagicMock()
    attr.name = name
    attr.attribute_type = kind
    return attr


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()

    client.views.get_all_names.return_value = (["All Sales"], ["My Draft"])
    client.subsets.get_all_names.return_value = ["Current Year", "All Months"]
    client.elements.get_element_attributes.return_value = [
        _attribute("Description", "String"),
        _attribute("Weight", "Numeric"),
    ]
    client.hierarchies.get_all_names.return_value = ["Region", "ByCountry"]
    client.hierarchies.get_default_member.return_value = "Total Region"
    client.elements.get_parents.return_value = ["Total Region"]
    client.elements.get_leaves_under_consolidation.return_value = ["France", "Spain"]

    client.server.get_product_version.return_value = "11.8.01000.10"
    client.monitoring.get_sessions.return_value = [{"ID": "1"}, {"ID": "2"}]
    client.monitoring.get_active_threads.return_value = [
        {
            "ID": 12,
            "Name": "Pseudo",
            "State": "Run",
            "Function": "ExecuteProcess",
            "ObjectName": "Load Sales",
        }
    ]

    process = MagicMock()
    process.name = "Load Sales"
    process.datasource_type = "None"
    process.datasource_data_source_name_for_server = ""
    process.datasource_view = ""
    process.has_security_access = False
    process.parameters = []
    process.prolog_procedure = SERVER_PROLOG
    process.metadata_procedure = ""
    process.data_procedure = ""
    process.epilog_procedure = ""
    client.processes.get.return_value = process
    client.processes.get_all_names.return_value = ["Load Sales"]

    cube = MagicMock()
    cube.name = "Sales"
    cube.has_rules = True
    cube.rules.text = BROKEN_RULES
    cube.dimensions = ["Region"]
    client.cubes.get.return_value = cube
    client.cubes.get_all_names_with_rules.return_value = ["Sales"]

    monkeypatch.setattr(
        tm1_connection_manager, "get_client", AsyncMock(return_value=client)
    )
    return client


async def _connection(db_session, organization_id, created_by):
    return await tm1_integration_service.create_connection(
        db_session,
        organization_id=organization_id,
        created_by=created_by,
        name="Dev",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )


async def _run(tool, db_session, org, admin, connection, **kwargs):
    return json.loads(
        await tool.execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            **kwargs,
        )
    )


# ------------------------------------------------------------- structure


@pytest.mark.asyncio
async def test_list_cube_views_splits_public_and_private(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        ListCubeViewsTool(), db_session, org, admin, connection, cube_name="Sales"
    )

    assert body["public_views"] == ["All Sales"]
    assert body["private_views"] == ["My Draft"]


@pytest.mark.asyncio
async def test_list_dimension_subsets_defaults_hierarchy_to_dimension(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        ListDimensionSubsetsTool(),
        db_session, org, admin, connection,
        dimension_name="Region",
    )

    assert body["hierarchy"] == "Region"
    assert body["count"] == 2
    _, kwargs = fake_tm1_client.subsets.get_all_names.call_args
    assert kwargs["hierarchy_name"] == "Region"


@pytest.mark.asyncio
async def test_get_dimension_attributes_returns_types_and_default_member(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        GetDimensionAttributesTool(),
        db_session, org, admin, connection,
        dimension_name="Region",
    )

    assert {"name": "Description", "type": "String"} in body["attributes"]
    assert body["default_member"] == "Total Region"
    assert body["hierarchies"] == ["Region", "ByCountry"]


@pytest.mark.asyncio
async def test_get_element_context_reports_consolidation(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        GetElementContextTool(),
        db_session, org, admin, connection,
        dimension_name="Region", element_name="EMEA",
    )

    assert body["is_consolidation"] is True
    assert body["leaf_count"] == 2
    assert body["parents"] == ["Total Region"]
    assert "Description" in body["attributes"]


@pytest.mark.asyncio
async def test_get_element_context_handles_leaf_without_children(
    db_session, tm1_credentials_key, fake_tm1_client
):
    # TM1 raises when asked for leaves under a leaf; that is an ordinary
    # answer, not a failure.
    fake_tm1_client.elements.get_leaves_under_consolidation.side_effect = RuntimeError(
        "not a consolidation"
    )

    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        GetElementContextTool(),
        db_session, org, admin, connection,
        dimension_name="Region", element_name="France",
    )

    assert body["is_consolidation"] is False
    assert body["leaves"] == []


@pytest.mark.asyncio
async def test_get_server_state_reports_threads(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(GetServerStateTool(), db_session, org, admin, connection)

    assert body["version"] == "11.8.01000.10"
    assert body["session_count"] == 2
    assert body["threads"][0]["object_name"] == "Load Sales"


@pytest.mark.asyncio
async def test_get_server_state_survives_blocked_monitoring(
    db_session, tm1_credentials_key, fake_tm1_client
):
    # Monitoring endpoints are the first thing a hardened TM1 blocks. The
    # version must still come back.
    fake_tm1_client.monitoring.get_sessions.side_effect = RuntimeError("forbidden")

    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(GetServerStateTool(), db_session, org, admin, connection)

    assert body["version"] == "11.8.01000.10"
    assert "sessions" in body["unavailable"]


# ------------------------------------------------------------------ diff


@pytest.mark.asyncio
async def test_diff_process_reports_identical(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        DiffProcessTool(),
        db_session, org, admin, connection,
        process_name="Load Sales", prolog=SERVER_PROLOG,
    )

    assert body["identical"] is True
    assert body["sections_compared"] == ["prolog"]


@pytest.mark.asyncio
async def test_diff_process_returns_unified_diff(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        DiffProcessTool(),
        db_session, org, admin, connection,
        process_name="Load Sales", prolog="sYear = '2027';\nnCount = 0;",
    )

    assert body["identical"] is False
    assert "prolog" in body["sections_differing"]
    assert "-sYear = '2026';" in body["diffs"]["prolog"]
    assert "+sYear = '2027';" in body["diffs"]["prolog"]


@pytest.mark.asyncio
async def test_diff_process_requires_a_section(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        DiffProcessTool(), db_session, org, admin, connection,
        process_name="Load Sales",
    )

    assert "error" in body


# ---------------------------------------------------------- health check


@pytest.mark.asyncio
async def test_health_check_combines_rules_and_processes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        RunModelHealthCheckTool(), db_session, org, admin, connection
    )

    assert body["totals"]["cubes_analysed"] == 1
    assert body["totals"]["critical_rule_findings"] == 1
    assert body["totals"]["processes_analysed"] == 1
    assert "critical" in body["verdict"]
    assert body["rules"][0]["cube"] == "Sales"


@pytest.mark.asyncio
async def test_health_check_can_skip_processes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        RunModelHealthCheckTool(), db_session, org, admin, connection,
        include_processes=False,
    )

    assert body["totals"]["processes_analysed"] == 0
    fake_tm1_client.processes.get_all_names.assert_not_called()


@pytest.mark.asyncio
async def test_health_check_reports_clean_model(
    db_session, tm1_credentials_key, fake_tm1_client
):
    fake_tm1_client.cubes.get_all_names_with_rules.return_value = []
    fake_tm1_client.processes.get_all_names.return_value = []

    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        RunModelHealthCheckTool(), db_session, org, admin, connection
    )

    assert body["verdict"] == "No findings in the objects analysed."


@pytest.mark.asyncio
async def test_health_check_survives_one_unreadable_cube(
    db_session, tm1_credentials_key, fake_tm1_client
):
    fake_tm1_client.cubes.get.side_effect = RuntimeError("connection reset")

    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    body = await _run(
        RunModelHealthCheckTool(), db_session, org, admin, connection
    )

    assert "connection reset" in body["rules"][0]["error"]


# ----------------------------------------------------------- permissions


@pytest.mark.asyncio
async def test_new_tools_require_tm1_read_permission(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _connection(db_session, org.id, admin.id)

    other_org = await create_organization(db_session)
    unprivileged = await create_user(db_session, organization_id=other_org.id)

    for tool in (
        ListCubeViewsTool(),
        ListDimensionSubsetsTool(),
        GetDimensionAttributesTool(),
        GetElementContextTool(),
        GetServerStateTool(),
        DiffProcessTool(),
        RunModelHealthCheckTool(),
    ):
        with pytest.raises(PermissionDeniedException):
            await tool.execute(
                db_session,
                organization_id=org.id,
                user_id=unprivileged.id,
                connection_id=str(connection.id),
                cube_name="Sales",
                dimension_name="Region",
                element_name="EMEA",
                process_name="Load Sales",
                prolog="x",
            )
