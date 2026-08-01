from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from TM1py import Process

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.core.exceptions import ConflictException, ValidationException
from src.repositories.tm1_change_repository import tm1_change_repository
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.deployment.change_service import change_service
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


def _make_cube(name, rule_text):
    cube = MagicMock()
    cube.name = name
    cube.dimensions = ["Region"]
    cube.has_rules = rule_text is not None
    cube.rules.text = rule_text
    return cube


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()

    client.cubes.get.return_value = _make_cube("Sales", "['A'] = N: 1;")
    client.cubes.check_rules.return_value = []

    client.processes.exists.return_value = False
    client.processes.compile_process.return_value = []
    client.processes.compile.return_value = []
    # Real TM1py body dict so Process.from_dict round-trips in rollback paths.
    client.processes.get.return_value = Process(
        name="Existing", prolog_procedure="# original"
    )

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


async def _setup(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Prod",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )
    return org, user, connection


@pytest.mark.asyncio
async def test_create_update_rules_draft(db_session, tm1_credentials_key, fake_tm1_client):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="update_rules",
        target_name="Sales",
        new_content={"rules": "['A'] = N: 2;"},
    )

    assert change.status == "draft"
    assert change.validation_errors is None
    # Not in metadata graph -> impact carries the run-extraction note.
    assert change.impact and "note" in change.impact[0]


@pytest.mark.asyncio
async def test_create_process_draft_with_compile_errors_cannot_execute(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)
    fake_tm1_client.processes.compile_process.return_value = [
        {"LineNumber": 1, "Message": "Syntax error"}
    ]

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
        new_content={"prolog": "bad code"},
    )

    assert change.validation_errors

    with pytest.raises(ValidationException):
        await change_service.execute_change(db_session, change, user.id)


@pytest.mark.asyncio
async def test_execute_update_rules_snapshots_and_applies(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="update_rules",
        target_name="Sales",
        new_content={"rules": "['A'] = N: 2;"},
    )

    result = await change_service.execute_change(db_session, change, user.id)

    assert result.status == "executed"
    assert result.previous_content == {"rules": "['A'] = N: 1;"}
    fake_tm1_client.cubes.update_or_create_rules.assert_called_once_with(
        "Sales", "['A'] = N: 2;"
    )


@pytest.mark.asyncio
async def test_execute_update_rules_check_failure_restores_snapshot(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="update_rules",
        target_name="Sales",
        new_content={"rules": "['A'] = N: broken"},
    )

    fake_tm1_client.cubes.check_rules.return_value = [
        {"Message": "Syntax error at 'broken'"}
    ]

    result = await change_service.execute_change(db_session, change, user.id)

    assert result.status == "failed"
    assert result.validation_errors
    # Applied the new rules, then restored the snapshot.
    calls = fake_tm1_client.cubes.update_or_create_rules.call_args_list
    assert calls[0].args == ("Sales", "['A'] = N: broken")
    assert calls[1].args == ("Sales", "['A'] = N: 1;")


@pytest.mark.asyncio
async def test_create_process_execute_and_rollback(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
        new_content={"prolog": "# hello"},
    )

    executed = await change_service.execute_change(db_session, change, user.id)
    assert executed.status == "executed"
    assert executed.previous_content == {"existed": False}
    fake_tm1_client.processes.update_or_create.assert_called_once()

    rolled_back = await change_service.rollback_change(db_session, executed)
    assert rolled_back.status == "rolled_back"
    fake_tm1_client.processes.delete.assert_called_once_with("zNew")


@pytest.mark.asyncio
async def test_execute_requires_draft_status(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
        new_content={"prolog": "# hello"},
    )

    await change_service.execute_change(db_session, change, user.id)

    with pytest.raises(ConflictException):
        await change_service.execute_change(db_session, change, user.id)

    with pytest.raises(ConflictException):
        # rolled_back is terminal: rollback only applies to executed changes
        rolled = await change_service.rollback_change(db_session, change)
        await change_service.rollback_change(db_session, rolled)


@pytest.mark.asyncio
async def test_identical_proposal_returns_the_same_draft(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    kwargs = dict(
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
        new_content={"prolog": "# hello"},
    )

    first = await change_service.create_change(db_session, **kwargs)
    second = await change_service.create_change(db_session, **kwargs)

    # One proposal, one draft — however many times it is submitted.
    assert first.id == second.id
    # The repeat short-circuits before any TM1 round trip.
    assert fake_tm1_client.processes.compile_process.call_count == 1


@pytest.mark.asyncio
async def test_revised_proposal_supersedes_the_previous_draft(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    base = dict(
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
    )

    first = await change_service.create_change(
        db_session, **base, new_content={"prolog": "# v1"}
    )
    second = await change_service.create_change(
        db_session, **base, new_content={"prolog": "# v2"}
    )

    assert first.id != second.id
    assert first.status == "superseded"
    assert first.superseded_by == second.id
    assert second.status == "draft"

    # A superseded draft is no longer executable.
    with pytest.raises(ConflictException):
        await change_service.execute_change(db_session, first, user.id)


@pytest.mark.asyncio
async def test_another_author_draft_is_left_alone(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)
    colleague = await create_user(db_session, org.id)

    base = dict(
        connection_id=connection.id,
        organization_id=org.id,
        change_type="create_process",
        target_name="zNew",
    )

    mine = await change_service.create_change(
        db_session, **base, created_by=user.id, new_content={"prolog": "# mine"}
    )
    theirs = await change_service.create_change(
        db_session,
        **base,
        created_by=colleague.id,
        new_content={"prolog": "# theirs"},
    )

    assert mine.status == "draft"
    assert theirs.status == "draft"


@pytest.mark.asyncio
async def test_case_mismatch_blocks_execution(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zNew",
        # The server dry-run returns clean; the static check is what fires.
        new_content={
            "prolog": "sCubeName = 'Sales';",
            "data": "CellPutN(1, sCubename, 'Actual');",
        },
    )

    assert change.validation_errors
    assert "sCubeName" in change.validation_errors[0]

    with pytest.raises(ValidationException):
        await change_service.execute_change(db_session, change, user.id)


@pytest.mark.asyncio
async def test_four_proposals_in_one_turn_leave_one_executable_draft(
    db_session, tm1_credentials_key, fake_tm1_client
):
    # Reproduces the observed live state: one agent turn emitting several
    # propose_process_update calls, each with different content, against
    # the same target. Four competing executable drafts is the danger.
    org, user, connection = await _setup(db_session)

    base = dict(
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="BuildProductDimension",
    )

    changes = [
        await change_service.create_change(
            db_session, **base, new_content={"prolog": f"# revision {n}"}
        )
        for n in range(4)
    ]

    assert len({c.id for c in changes}) == 4

    open_drafts = await tm1_change_repository.list_open_drafts(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="BuildProductDimension",
    )

    assert [d.id for d in open_drafts] == [changes[-1].id]
    # Each retired draft points at whatever replaced it.
    for earlier, later in zip(changes, changes[1:]):
        assert earlier.status == "superseded"
        assert earlier.superseded_by == later.id


@pytest.mark.asyncio
async def test_invented_datasource_variables_block_execution(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org, user, connection = await _setup(db_session)

    change = await change_service.create_change(
        db_session,
        connection_id=connection.id,
        organization_id=org.id,
        created_by=user.id,
        change_type="create_process",
        target_name="zLoad",
        new_content={
            "variables": [{"name": "v1", "type": "String"}],
            "data": "sOrg = Organization;\nnAmt = vCashFlow_Direct_Method_;",
        },
    )

    assert change.validation_errors
    assert "Organization" in change.validation_errors[0]

    with pytest.raises(ValidationException):
        await change_service.execute_change(db_session, change, user.id)
