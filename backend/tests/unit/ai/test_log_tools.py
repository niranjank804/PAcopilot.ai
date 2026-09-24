import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.logs import (
    GetMessageLogTool,
    GetProcessErrorLogTool,
    GetTransactionLogTool,
    ListProcessErrorLogsTool,
    MapLogErrorToCodeTool,
    parse_timestamp,
)
from src.ai.tools.tm1.processes import SearchProcessCodeTool
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.service import tm1_integration_service
from src.tm1.services.log_service import (
    DEFAULT_ROWS,
    MAX_ROWS,
    clamp,
    parse_error_locations,
    truncate_log,
)
from tests.fixtures.factories import create_org_admin, create_organization, create_user

ERROR_LOG = """
Error: Prolog procedure line (3): Invalid key: Dimension Name: "Region"
Error: Data procedure line (2): Division by zero
"""

PROLOG = "sHello = 'x';\nsWorld = 'y';\nCellPutN(1, 'Sales', 'Nowhere');\nsAfter = 'z';"
DATA = "nValue = 1;\nnRatio = nValue / 0;\nItemSkip;"


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

    client.server.get_message_log_entries.return_value = [
        {"TimeStamp": "2026-09-22T06:00:00Z", "Level": "ERROR", "Message": "boom"}
    ]
    client.server.get_transaction_log_entries.return_value = [
        {"TimeStamp": "2026-09-22T06:00:00Z", "User": "admin", "Cube": "Sales"}
    ]

    client.processes.get_error_log_filenames.return_value = [
        "TM1ProcessError_20260922_Load_Sales.log"
    ]
    client.processes.get_error_log_file_content.return_value = ERROR_LOG
    client.processes.search_string_in_code.return_value = ["Load Sales", "Clear Sales"]

    process = MagicMock()
    process.name = "Load Sales"
    process.datasource_type = "TM1CubeView"
    process.datasource_data_source_name_for_server = "Sales"
    process.datasource_view = "All"
    process.has_security_access = False
    process.parameters = []
    process.prolog_procedure = PROLOG
    process.metadata_procedure = ""
    process.data_procedure = DATA
    process.epilog_procedure = ""
    client.processes.get.return_value = process

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


# --------------------------------------------------------------- pure helpers


def test_parse_error_locations_extracts_section_and_line():
    found = parse_error_locations(ERROR_LOG)

    assert len(found) == 2
    assert found[0]["section"] == "prolog"
    assert found[0]["line_number"] == 3
    assert "Invalid key" in found[0]["message"]
    assert found[1]["section"] == "data"
    assert found[1]["line_number"] == 2


def test_parse_error_locations_returns_empty_when_no_line_reference():
    # An aborted process often logs only a ProcessQuit. That is a normal
    # outcome, not a parse failure.
    assert parse_error_locations("Process quit on user request") == []


def test_clamp_bounds_row_counts():
    assert clamp(None) == DEFAULT_ROWS
    assert clamp(0) == DEFAULT_ROWS
    assert clamp(-5) == DEFAULT_ROWS
    assert clamp(10) == 10
    assert clamp(MAX_ROWS * 10) == MAX_ROWS


def test_truncate_log_marks_truncation():
    assert truncate_log("short", limit=100) == "short"

    out = truncate_log("x" * 500, limit=100)
    assert out.startswith("x" * 100)
    assert "truncated" in out


def test_parse_timestamp_accepts_iso_and_tolerates_junk():
    assert parse_timestamp("2026-09-22T06:00:00Z") is not None
    assert parse_timestamp("not a date") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None


# ---------------------------------------------------------------------- tools


@pytest.mark.asyncio
async def test_get_message_log_returns_entries(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await GetMessageLogTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            top=10,
        )
    )

    assert body["count"] == 1
    assert body["entries"][0]["Level"] == "ERROR"


@pytest.mark.asyncio
async def test_get_message_log_caps_requested_rows(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    await GetMessageLogTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        top=100000,
    )

    _, kwargs = fake_tm1_client.server.get_message_log_entries.call_args
    assert kwargs["top"] == MAX_ROWS


@pytest.mark.asyncio
async def test_get_transaction_log_passes_cube_filter(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await GetTransactionLogTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            cube="Sales",
        )
    )

    assert body["count"] == 1
    _, kwargs = fake_tm1_client.server.get_transaction_log_entries.call_args
    assert kwargs["cube"] == "Sales"


@pytest.mark.asyncio
async def test_list_process_error_logs(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await ListProcessErrorLogsTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            process_name="Load Sales",
        )
    )

    assert body["count"] == 1
    assert body["log_files"][0].endswith(".log")


@pytest.mark.asyncio
async def test_get_process_error_log_reports_when_none_exists(
    db_session, tm1_credentials_key, fake_tm1_client
):
    fake_tm1_client.processes.get_error_log_filenames.return_value = []

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await GetProcessErrorLogTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            process_name="Load Sales",
        )
    )

    assert body["found"] is False
    assert "not failed" in body["message"]


@pytest.mark.asyncio
async def test_map_log_error_to_code_resolves_lines_in_both_sections(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await MapLogErrorToCodeTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            process_name="Load Sales",
        )
    )

    assert body["resolved"] is True
    assert body["error_count"] == 2

    prolog_error, data_error = body["errors"]

    # Prolog line 3 of PROLOG is the CellPutN.
    assert prolog_error["section"] == "prolog"
    assert prolog_error["code_line"] == "CellPutN(1, 'Sales', 'Nowhere');"

    # Data line 2 of DATA is the division.
    assert data_error["section"] == "data"
    assert data_error["code_line"] == "nRatio = nValue / 0;"

    # The error line is flagged inside its context window.
    flagged = [c for c in prolog_error["context"] if c["is_error_line"]]
    assert len(flagged) == 1
    assert flagged[0]["line_number"] == 3


@pytest.mark.asyncio
async def test_map_log_error_to_code_flags_line_outside_current_code(
    db_session, tm1_credentials_key, fake_tm1_client
):
    # The process has been edited since it failed, so the logged line no
    # longer exists. We must say so rather than resolve the wrong line.
    fake_tm1_client.processes.get_error_log_file_content.return_value = (
        "Error: Prolog procedure line (999): something"
    )

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await MapLogErrorToCodeTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            process_name="Load Sales",
        )
    )

    assert body["errors"][0]["code_line"] is None
    assert "edited" in body["errors"][0]["note"]


@pytest.mark.asyncio
async def test_map_log_error_to_code_handles_log_without_line_numbers(
    db_session, tm1_credentials_key, fake_tm1_client
):
    fake_tm1_client.processes.get_error_log_file_content.return_value = (
        "Process quit on user request"
    )

    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await MapLogErrorToCodeTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            process_name="Load Sales",
        )
    )

    assert body["resolved"] is False
    assert "no line number" in body["message"]
    assert "Process quit" in body["log"]


@pytest.mark.asyncio
async def test_search_process_code_returns_matches(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await SearchProcessCodeTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            search_string="CellPutN",
        )
    )

    assert body["match_count"] == 2
    assert "Load Sales" in body["processes"]


@pytest.mark.asyncio
async def test_search_process_code_rejects_empty_string(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    body = json.loads(
        await SearchProcessCodeTool().execute(
            db_session,
            organization_id=org.id,
            user_id=admin.id,
            connection_id=str(connection.id),
            search_string="   ",
        )
    )

    assert "error" in body
    fake_tm1_client.processes.search_string_in_code.assert_not_called()


@pytest.mark.asyncio
async def test_log_tools_require_tm1_read_permission(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)

    other_org = await create_organization(db_session)
    unprivileged = await create_user(db_session, organization_id=other_org.id)

    for tool in (
        GetMessageLogTool(),
        GetTransactionLogTool(),
        ListProcessErrorLogsTool(),
        GetProcessErrorLogTool(),
        MapLogErrorToCodeTool(),
        SearchProcessCodeTool(),
    ):
        with pytest.raises(PermissionDeniedException):
            await tool.execute(
                db_session,
                organization_id=org.id,
                user_id=unprivileged.id,
                connection_id=str(connection.id),
                process_name="Load Sales",
                search_string="x",
            )
