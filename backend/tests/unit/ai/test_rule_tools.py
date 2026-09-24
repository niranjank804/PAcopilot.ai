import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.rules import (
    AnalyzeCubeRulesTool,
    AuditModelRulesTool,
    SearchRulesTool,
    TraceCellCalculationTool,
)
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_org_admin, create_organization, create_user

BROKEN_RULES = """
SKIPCHECK;
['Gross Margin'] = N: ['Revenue'] - ['COGS'];
FEEDERS;
['Revenue'] => ['Something Else'];
"""

CLEAN_RULES = """
SKIPCHECK;
['Gross Margin'] = N: ['Revenue'] - ['COGS'];
FEEDERS;
['Revenue'] => ['Gross Margin'];
"""

RULES_BY_CUBE = {"Sales": BROKEN_RULES, "Expense": CLEAN_RULES}


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

    def get_cube(name, **_):
        cube = MagicMock()
        cube.name = name
        text = RULES_BY_CUBE.get(name)
        cube.has_rules = text is not None
        cube.rules.text = text
        cube.dimensions = ["Region", "Month"]
        return cube

    client.cubes.get.side_effect = get_cube
    client.cubes.get_all_names_with_rules.return_value = ["Sales", "Expense"]

    matched = MagicMock()
    matched.name = "Sales"
    client.cubes.search_for_rule_substring.return_value = [matched]

    monkeypatch.setattr(
        tm1_connection_manager, "get_client", AsyncMock(return_value=client)
    )
    return client


async def _create_connection(db_session, organization_id, created_by):
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


@pytest.mark.asyncio
async def test_analyze_cube_rules_reports_unfed_calculation(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await AnalyzeCubeRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube_name="Sales",
        )
    )

    assert body["has_rules"] is True
    assert body["summary"]["critical"] == 1
    assert body["findings"][0]["code"] == "unfed_calculation"
    assert body["findings"][0]["line_number"] == 3


@pytest.mark.asyncio
async def test_analyze_cube_rules_is_quiet_on_clean_rules(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await AnalyzeCubeRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube_name="Expense",
        )
    )

    assert body["findings"] == []


@pytest.mark.asyncio
async def test_analyze_cube_rules_handles_cube_without_rules(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await AnalyzeCubeRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube_name="NoRules",
        )
    )

    assert body["has_rules"] is False


@pytest.mark.asyncio
async def test_trace_cell_calculation_explains_a_zero_total(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await TraceCellCalculationTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube_name="Sales",
            elements=["Gross Margin", "EMEA"],
        )
    )

    assert body["calculated"] is True
    assert body["is_fed"] is False
    assert "read zero" in body["warning"]


@pytest.mark.asyncio
async def test_trace_cell_calculation_rejects_empty_elements(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await TraceCellCalculationTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube_name="Sales",
            elements=[],
        )
    )

    assert "error" in body


@pytest.mark.asyncio
async def test_search_rules_returns_matching_cubes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await SearchRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            search_string="COGS",
        )
    )

    assert body["match_count"] == 1
    assert body["cubes"] == ["Sales"]


@pytest.mark.asyncio
async def test_audit_model_rules_ranks_cubes_by_severity(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await AuditModelRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
        )
    )

    assert body["cubes_analysed"] == 2
    # Only the broken cube is reported; the clean one is omitted.
    assert body["cubes_with_findings"] == 1
    assert body["total_critical"] == 1
    assert body["results"][0]["cube"] == "Sales"


@pytest.mark.asyncio
async def test_audit_model_rules_survives_one_unreadable_cube(
    db_session, tm1_credentials_key, fake_tm1_client
):
    def explode(name, **_):
        if name == "Expense":
            raise RuntimeError("connection reset")
        cube = MagicMock()
        cube.name = name
        cube.has_rules = True
        cube.rules.text = BROKEN_RULES
        return cube

    fake_tm1_client.cubes.get.side_effect = explode

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await AuditModelRulesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
        )
    )

    cubes = {r["cube"]: r for r in body["results"]}
    assert "Sales" in cubes
    assert "connection reset" in cubes["Expense"]["error"]


@pytest.mark.asyncio
async def test_rule_tools_require_tm1_read_permission(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    other_org = await create_organization(db_session)
    unprivileged = await create_user(db_session, organization_id=other_org.id)

    for tool in (
        AnalyzeCubeRulesTool(),
        TraceCellCalculationTool(),
        SearchRulesTool(),
        AuditModelRulesTool(),
    ):
        with pytest.raises(PermissionDeniedException):
            await tool.execute(
                db_session,
                organization_id=org.id,
                user_id=unprivileged.id,
                connection_id=str(connection.id),
                cube_name="Sales",
                elements=["Gross Margin"],
                search_string="x",
            )
