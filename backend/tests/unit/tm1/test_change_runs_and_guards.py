"""Approved process runs, and the guards around applying and rolling back.

A run is the one change with no undo, and the guards below are what keep a
change from overwriting work it never saw: a process created between draft
and approval, an edit made after a change was applied, a check that fails
by raising rather than by reporting findings.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from TM1py import Process

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.core.exceptions import ConflictException, ValidationException
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.deployment.change_service import change_service, validate_run_parameters
from src.tm1.exceptions import TM1ConnectionError
from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user


@pytest.fixture
def tm1_credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None
    yield
    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


def _process(name="Load", parameters=None, prolog="# original"):
    process = Process(name=name, prolog_procedure=prolog)
    for p in parameters or []:
        process.add_parameter(p["Name"], p.get("Prompt", ""), p.get("Value", ""), p.get("Type", "String"))
    return process


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    rules = {"text": "['A'] = N: 1;"}

    def get_cube(_name):
        cube = MagicMock()
        cube.name = "Sales"
        cube.dimensions = ["Region"]
        cube.has_rules = True
        cube.rules.text = rules["text"]
        return cube

    def update_rules(cube):
        rules["text"] = cube.rules.text if hasattr(cube.rules, "text") else str(cube.rules)

    client.rules_state = rules
    client.cubes.get.side_effect = get_cube
    client.cubes.check_rules.return_value = []
    client.processes.exists.return_value = False
    client.processes.compile_process.return_value = []
    client.processes.compile.return_value = []
    client.processes.get.return_value = _process(
        parameters=[{"Name": "pYear", "Type": "String"}, {"Name": "pCount", "Type": "Numeric", "Value": 0}]
    )
    client.processes.execute_with_return.return_value = (True, "CompletedSuccessfully", None)

    monkeypatch.setattr(tm1_connection_manager, "get_client", AsyncMock(return_value=client))
    return client


async def _setup(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Dev",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )
    return org, user, connection


async def _draft(db_session, org, user, connection, change_type, target, content):
    return await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type=change_type,
        target_name=target,
        new_content=content,
    )


# --------------------------------------------------------------- run plans


def test_run_parameters_are_checked_before_anyone_approves():
    definitions = [{"name": "pYear", "type": "String"}, {"name": "pCount", "type": "Numeric"}]

    assert validate_run_parameters(definitions, {"pYear": "2026", "pCount": "3"}) == []
    assert "no parameter 'pMonth'" in validate_run_parameters(definitions, {"pMonth": "1"})[0]
    assert "numeric" in validate_run_parameters(definitions, {"pCount": "three"})[0]


def test_a_parameter_tm1py_reserves_is_refused_at_draft_time():
    # It used to pass validation, be approved, then fail the run with a 500.
    problems = validate_run_parameters([{"name": "timeout", "type": "String"}], {"timeout": "5"})
    assert problems and "cannot be passed" in problems[0]


# ---------------------------------------------------------------- runs


@pytest.mark.asyncio
async def test_an_approved_run_runs_once_and_records_what_tm1_said(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "run_process", "Load",
                          {"parameters": {"pYear": "2026"}})
    assert change.status == "draft" and not change.validation_errors

    done = await change_service.execute_change(db_session, change, user.id)

    assert done.status == "executed"
    assert done.execution_result["success"] is True
    client.processes.execute_with_return.assert_called_once()
    assert client.processes.execute_with_return.call_args.kwargs["pYear"] == "2026"


@pytest.mark.asyncio
async def test_a_failed_run_is_recorded_with_its_error_log(db_session, tm1_credentials_key, client):
    org, user, connection = await _setup(db_session)
    client.processes.execute_with_return.return_value = (False, "Aborted", "TM1ProcessError_Load.log")
    client.processes.get_error_log_file_content.return_value = "Error: Data procedure line (12): bad"

    change = await _draft(db_session, org, user, connection, "run_process", "Load", {"parameters": {}})
    done = await change_service.execute_change(db_session, change, user.id)

    assert done.status == "failed"
    assert done.execution_result["error_log_file"] == "TM1ProcessError_Load.log"
    assert "Aborted" in done.error_message


@pytest.mark.asyncio
async def test_a_run_that_cannot_start_is_recorded_not_a_server_error(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "run_process", "Load", {"parameters": {}})
    client.processes.execute_with_return.side_effect = RuntimeError("process vanished")

    done = await change_service.execute_change(db_session, change, user.id)

    assert done.status == "failed"
    assert done.execution_result == {"success": False, "status": "NotStarted"}


@pytest.mark.asyncio
async def test_a_run_that_times_out_says_it_may_have_written_data(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "run_process", "Load", {"parameters": {}})
    client.processes.execute_with_return.side_effect = TM1ConnectionError("no answer")

    done = await change_service.execute_change(db_session, change, user.id)

    assert done.status == "failed"
    assert "may have" in done.error_message


@pytest.mark.asyncio
async def test_a_run_cannot_be_rolled_back(db_session, tm1_credentials_key, client):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "run_process", "Load", {"parameters": {}})
    done = await change_service.execute_change(db_session, change, user.id)

    with pytest.raises(ConflictException, match="cannot be rolled back"):
        await change_service.rollback_change(db_session, done)


@pytest.mark.asyncio
async def test_a_run_with_bad_parameters_cannot_be_approved(db_session, tm1_credentials_key, client):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "run_process", "Load",
                          {"parameters": {"pCount": "lots"}})

    assert change.validation_errors
    with pytest.raises(ValidationException):
        await change_service.execute_change(db_session, change, user.id)
    client.processes.execute_with_return.assert_not_called()


# -------------------------------------------------------------- guards


@pytest.mark.asyncio
async def test_create_refuses_when_the_name_was_taken_after_the_draft(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    change = await _draft(db_session, org, user, connection, "create_process", "zNew", {"prolog": "# hi"})

    client.processes.exists.return_value = True  # someone created it meanwhile

    with pytest.raises(ConflictException, match="created after"):
        await change_service.execute_change(db_session, change, user.id)
    client.processes.update_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_a_compile_that_raises_after_an_update_restores_the_previous_version(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    client.processes.exists.return_value = True
    change = await _draft(db_session, org, user, connection, "update_process", "Load", {"prolog": "# new"})
    client.processes.compile.side_effect = RuntimeError("TM1 went away mid-check")

    with pytest.raises(RuntimeError):
        await change_service.execute_change(db_session, change, user.id)

    # Applied, then the original put back.
    assert client.processes.update_or_create.call_count == 2
    restored = client.processes.update_or_create.call_args_list[-1].args[0]
    assert restored.prolog_procedure.endswith("# original")


@pytest.mark.asyncio
async def test_rollback_refuses_to_overwrite_a_process_edited_since(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    client.processes.exists.return_value = True
    change = await _draft(db_session, org, user, connection, "update_process", "Load", {"prolog": "# new"})
    done = await change_service.execute_change(db_session, change, user.id)
    assert done.status == "executed"

    # Someone edits the process in TM1 after the change was applied.
    client.processes.get.return_value = _process(prolog="# someone else's later fix")
    client.processes.update_or_create.reset_mock()

    with pytest.raises(ConflictException, match="edited since"):
        await change_service.rollback_change(db_session, done)
    client.processes.update_or_create.assert_not_called()


@pytest.mark.asyncio
async def test_rollback_restores_when_nothing_changed_since(db_session, tm1_credentials_key, client):
    org, user, connection = await _setup(db_session)
    client.processes.exists.return_value = True
    change = await _draft(db_session, org, user, connection, "update_process", "Load", {"prolog": "# new"})
    done = await change_service.execute_change(db_session, change, user.id)

    rolled_back = await change_service.rollback_change(db_session, done)

    assert rolled_back.status == "rolled_back"


@pytest.mark.asyncio
async def test_restoring_a_deleted_process_refuses_if_the_name_exists_again(
    db_session, tm1_credentials_key, client
):
    org, user, connection = await _setup(db_session)
    client.processes.exists.return_value = True
    change = await _draft(db_session, org, user, connection, "delete_process", "Load", None)
    done = await change_service.execute_change(db_session, change, user.id)
    assert done.status == "executed"

    # exists() is still True: a process of that name is there again.
    with pytest.raises(ConflictException, match="exists again"):
        await change_service.rollback_change(db_session, done)
