"""The diagnostic, exploration and development tools the agents use.

TM1 itself is replaced by the service functions the tools call, so each
test pins what a tool does with what TM1 answered: which evidence it marks
verified, what it reports as missing, and that validating code never saves
it.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.development import ValidateProcessCodeTool
from src.ai.tools.tm1.diagnostics import DiagnoseProcessFailureTool
from src.ai.tools.tm1.explore import GetProcessCallTreeTool, SearchModelObjectsTool
from src.core.config import settings
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.exceptions import TM1NotFoundError
from src.tm1.service import tm1_integration_service
from src.tm1.services import cube_service, dimension_service, log_service, process_service
from src.tm1.services.process_service import ProcessInfo
from tests.fixtures.factories import create_org_admin


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(tm1_connection_manager, "get_client", AsyncMock(return_value=client))
    return client


def _process(name, prolog="", data="", parameters=None):
    return ProcessInfo(
        name=name,
        datasource_type="None",
        datasource_name="",
        datasource_view="",
        has_security_access=False,
        parameter_names=[p["name"] for p in parameters or []],
        prolog=prolog,
        metadata="",
        data=data,
        epilog="",
        parameters=parameters or [],
        variables=[],
        datasource={},
    )


async def _setup(db_session):
    org, admin = await create_org_admin(db_session)
    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=admin.id,
        name="Dev",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )
    return org, admin, connection


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


@pytest.mark.asyncio
async def test_diagnosis_maps_the_error_log_to_code_and_marks_its_evidence(
    db_session, tm1_credentials_key, client, monkeypatch
):
    org, admin, connection = await _setup(db_session)
    load = _process(
        "Load Sales",
        prolog="# Load\nnRows = 0;\n",
        data="CellPutN(vValue, 'Sales', vRegion, vMonth);\n",
    )
    monkeypatch.setattr(process_service, "get_process", AsyncMock(return_value=load))
    monkeypatch.setattr(
        log_service,
        "list_process_error_logs",
        AsyncMock(return_value=["TM1ProcessError_20261003_Load Sales.log"]),
    )
    monkeypatch.setattr(
        log_service,
        "get_process_error_log",
        AsyncMock(return_value='Error: Data procedure line (1): "Nowhere" : member not found'),
    )
    monkeypatch.setattr(log_service, "get_message_log", AsyncMock(return_value=[]))

    result = await _run(DiagnoseProcessFailureTool(), db_session, org, admin, connection,
                        process_name="Load Sales")

    assert result["process"] == "Load Sales"
    assert "Sales" in result["writes_cubes"]
    assert result["error_log"]["file"].startswith("TM1ProcessError")
    assert result["error_log"]["errors"], result["error_log"]
    # The tool never states the cause: it is the model's inference, labelled so.
    assert result["evidence"]["inferred"]
    assert result["evidence"]["verified"]


@pytest.mark.asyncio
async def test_call_tree_follows_calls_and_reports_a_missing_process(
    db_session, tm1_credentials_key, client, monkeypatch
):
    org, admin, connection = await _setup(db_session)
    processes = {
        "Master": _process("Master", prolog="ExecuteProcess('Child');\n"),
        "Child": _process("Child", prolog="ExecuteProcess('Ghost');\n"),
    }

    async def get_process(_client, _cid, name, **_kw):
        if name not in processes:
            raise TM1NotFoundError(f"Process '{name}' not found.")
        return processes[name]

    monkeypatch.setattr(process_service, "get_process", get_process)

    result = await _run(GetProcessCallTreeTool(), db_session, org, admin, connection,
                        process_name="Master")
    text = json.dumps(result)

    assert "Child" in text
    assert "Ghost" in text  # called, but does not exist — reported, not dropped


@pytest.mark.asyncio
async def test_search_finds_objects_by_part_of_their_name(
    db_session, tm1_credentials_key, client, monkeypatch
):
    org, admin, connection = await _setup(db_session)
    monkeypatch.setattr(cube_service, "list_cubes", AsyncMock(return_value=["Sales", "Headcount", "Sales Plan"]))
    monkeypatch.setattr(dimension_service, "list_dimensions", AsyncMock(return_value=["Region"]))
    monkeypatch.setattr(process_service, "list_processes", AsyncMock(return_value=["Load Sales"]))

    result = await _run(SearchModelObjectsTool(), db_session, org, admin, connection,
                        query="sales", object_types=["cube", "dimension", "process"])

    names = {(r["type"], r["name"]) for r in result["results"]}
    assert ("cube", "Sales") in names and ("cube", "Sales Plan") in names
    assert ("process", "Load Sales") in names
    assert not any(r["name"] == "Headcount" for r in result["results"])


@pytest.mark.asyncio
async def test_validating_code_compiles_it_without_saving_anything(
    db_session, tm1_credentials_key, client, monkeypatch
):
    org, admin, connection = await _setup(db_session)
    monkeypatch.setattr(process_service, "process_exists", AsyncMock(return_value=False))
    dryrun = AsyncMock(return_value=[{"Procedure": "Prolog", "LineNumber": 1, "Message": "Syntax error"}])
    monkeypatch.setattr(process_service, "compile_process_dryrun", dryrun)
    save = AsyncMock()
    monkeypatch.setattr(process_service, "update_or_create_process", save)

    result = await _run(ValidateProcessCodeTool(), db_session, org, admin, connection,
                        process_name="zNew", prolog="nX = ;")

    dryrun.assert_awaited_once()
    save.assert_not_awaited()
    assert "Syntax error" in json.dumps(result)


@pytest.mark.asyncio
async def test_diagnosis_classifies_checks_and_adds_what_changed_around_it(
    db_session, tm1_credentials_key, client, monkeypatch
):
    from datetime import datetime, timezone

    from src.database.models.tm1_change import TM1Change
    from src.tm1.services import structure_service

    org, admin, connection = await _setup(db_session)
    load = _process("Load Sales", data="CellPutN(vValue, 'Sales', vYear, vMonth);\n")
    monkeypatch.setattr(process_service, "get_process", AsyncMock(return_value=load))
    monkeypatch.setattr(log_service, "list_process_error_logs", AsyncMock(return_value=["TM1ProcessError_x.log"]))
    monkeypatch.setattr(
        log_service,
        "get_process_error_log",
        AsyncMock(return_value='Error: Data procedure line (1): Invalid key: Dimension Name: "Year", Element Name (Key): "2027"'),
    )
    monkeypatch.setattr(log_service, "get_message_log", AsyncMock(return_value=[]))

    async def object_exists(_client, _cid, kind, name, dimension_name=None, **_):
        return kind == "dimension"  # Year exists; 2027 does not

    monkeypatch.setattr(structure_service, "object_exists", object_exists)

    # Someone changed the process through PA-Copilot yesterday.
    db_session.add(TM1Change(
        connection_id=connection.id, organization_id=org.id, created_by=admin.id,
        change_type="update_process", target_name="Load Sales", status="executed",
        new_content={"data": "x"},
        executed_by=admin.id, executed_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    result = await _run(DiagnoseProcessFailureTool(), db_session, org, admin, connection,
                        process_name="Load Sales")

    failure = result["failures"][0]
    assert failure["category"] == "element_not_found"
    assert failure["entities"] == {"dimension": "Year", "element": "2027"}
    assert failure["checks"][0]["result"].startswith("no — it is still missing")
    assert result["context"]["recent_changes_through_pa_copilot"][0]["type"] == "update_process"
    # Never mapped: says so instead of claiming nothing runs it.
    assert result["context"]["run_by"] is None
    assert any("dependency map" in u for u in result["evidence"]["unknown"])


@pytest.mark.asyncio
async def test_after_approval_the_agent_reads_what_actually_happened(
    db_session, tm1_credentials_key, client
):
    from datetime import datetime, timezone

    from src.ai.tools.tm1.diagnostics import GetChangeStatusTool
    from src.database.models.tm1_change import TM1Change

    org, admin, connection = await _setup(db_session)
    run = TM1Change(
        connection_id=connection.id, organization_id=org.id, created_by=admin.id,
        change_type="run_process", target_name="Load Sales", status="failed",
        new_content={"parameters": {}},
        executed_by=admin.id, executed_at=datetime.now(timezone.utc),
        execution_result={"success": False, "status": "Aborted", "error_log_file": "x.log"},
        error_message="TM1 reported Aborted.",
    )
    db_session.add(run)
    await db_session.flush()

    by_id = await _run(GetChangeStatusTool(), db_session, org, admin, connection, change_id=str(run.id))
    by_name = await _run(GetChangeStatusTool(), db_session, org, admin, connection, target_name="load sales")

    assert by_id["changes"][0]["status"] == "failed"
    assert by_id["changes"][0]["execution_result"]["status"] == "Aborted"
    assert by_name["changes"][0]["change_id"] == str(run.id)


@pytest.mark.asyncio
async def test_change_status_never_shows_another_organizations_changes(
    db_session, tm1_credentials_key, client
):
    from src.ai.tools.tm1.diagnostics import GetChangeStatusTool
    from src.database.models.tm1_change import TM1Change

    org, admin, connection = await _setup(db_session)
    other_org, other_admin, other_connection = await _setup(db_session)
    theirs = TM1Change(
        connection_id=other_connection.id, organization_id=other_org.id, created_by=other_admin.id,
        change_type="run_process", target_name="Load Sales", status="draft",
        new_content={},
    )
    db_session.add(theirs)
    await db_session.flush()

    from src.core.exceptions import NotFoundException

    with pytest.raises(NotFoundException):
        # Their connection is not ours: refused before any change is read.
        await GetChangeStatusTool().execute(
            db_session, organization_id=org.id, user_id=admin.id,
            connection_id=str(other_connection.id), change_id=str(theirs.id),
        )
