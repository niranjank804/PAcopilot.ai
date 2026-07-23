from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.tm1.client.connection_manager import tm1_connection_manager
from src.tm1.metadata.extractor import extract_metadata
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


def _make_cube(name, dimensions, rule_text=None):
    cube = MagicMock()
    cube.name = name
    cube.dimensions = dimensions
    cube.has_rules = rule_text is not None
    cube.rules.text = rule_text
    return cube


def _make_dimension(name, hierarchy_names):
    dimension = MagicMock()
    dimension.name = name
    dimension.hierarchy_names = hierarchy_names
    return dimension


def _make_process(name, datasource_type, datasource_name, data_code):
    process = MagicMock()
    process.name = name
    process.datasource_type = datasource_type
    process.datasource_data_source_name_for_server = datasource_name
    process.datasource_view = ""
    process.has_security_access = False
    process.parameters = []
    process.prolog_procedure = ""
    process.metadata_procedure = ""
    process.data_procedure = data_code
    process.epilog_procedure = ""
    return process


def _make_task(process_name):
    task = MagicMock()
    task.process_name = process_name
    return task


def _make_chore(name, active, process_names):
    chore = MagicMock()
    chore.name = name
    chore.active = active
    chore.tasks = [_make_task(process_name) for process_name in process_names]
    return chore


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()

    # 2 cubes; Sales has rules referencing Expense plus a stale 'Missing' cube
    client.cubes.get_all_names.return_value = ["Sales", "Expense"]
    cubes_by_name = {
        "Sales": _make_cube(
            "Sales",
            ["Region", "Product"],
            rule_text="['Total'] = N: DB('Expense', !Region) + DB('Missing', 'x');",
        ),
        "Expense": _make_cube("Expense", ["Region", "Account"]),
    }
    client.cubes.get.side_effect = lambda name: cubes_by_name[name]

    # 3 dimensions, 4 hierarchies in total
    dimensions_by_name = {
        "Region": _make_dimension("Region", ["Region"]),
        "Product": _make_dimension("Product", ["Product", "Product Alt"]),
        "Account": _make_dimension("Account", ["Account"]),
    }
    client.dimensions.get.side_effect = lambda name: dimensions_by_name[name]

    # 1 TI process reading Expense (cube-view datasource) and writing Sales,
    # plus a write to a stale 'Missing' cube that must be skipped
    client.processes.get_all_names.return_value = ["Load Sales"]
    client.processes.get.return_value = _make_process(
        "Load Sales",
        datasource_type="TM1CubeView",
        datasource_name="Expense",
        data_code="CellPutN(1, 'Sales', 'NA'); CellPutN(2, 'Missing', 'x');",
    )

    # 1 chore running the known process plus a stale reference to a
    # process that no longer exists, which must be skipped
    client.chores.get_all_names.return_value = ["Load Sales Nightly"]
    client.chores.get.return_value = _make_chore(
        "Load Sales Nightly",
        active=True,
        process_names=["Load Sales", "Missing Process"],
    )

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


async def _relationship_type_counts(db_session, connection_id):
    relationships = (
        (
            await db_session.execute(
                select(TM1Relationship).where(
                    TM1Relationship.connection_id == connection_id
                )
            )
        )
        .scalars()
        .all()
    )

    counts: dict[str, int] = {}

    for relationship in relationships:
        counts[relationship.relationship_type] = (
            counts.get(relationship.relationship_type, 0) + 1
        )

    return counts


@pytest.mark.asyncio
async def test_extract_metadata_creates_objects_and_relationships(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    summary = await extract_metadata(db_session, connection.id, org.id)

    # 2 cubes + 3 dimensions + 4 hierarchies + 1 process + 1 chore
    assert summary.objects_created == 11
    # 4 uses_dimension + 4 contains_hierarchy + 1 references_cube
    # + 1 reads_cube + 1 updates_cube + 1 runs_process
    assert summary.relationships_created == 12

    counts = await _relationship_type_counts(db_session, connection.id)
    assert counts == {
        "uses_dimension": 4,
        "contains_hierarchy": 4,
        "references_cube": 1,
        "reads_cube": 1,
        "updates_cube": 1,
        "runs_process": 1,
    }


@pytest.mark.asyncio
async def test_extract_metadata_skips_references_to_unknown_cubes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    await extract_metadata(db_session, connection.id, org.id)

    missing = (
        (
            await db_session.execute(
                select(TM1Object).where(
                    TM1Object.connection_id == connection.id,
                    TM1Object.name == "Missing",
                )
            )
        )
        .scalars()
        .all()
    )
    assert missing == []


@pytest.mark.asyncio
async def test_extract_metadata_skips_chore_tasks_for_unknown_processes(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    await extract_metadata(db_session, connection.id, org.id)

    missing_process = (
        (
            await db_session.execute(
                select(TM1Object).where(
                    TM1Object.connection_id == connection.id,
                    TM1Object.name == "Missing Process",
                )
            )
        )
        .scalars()
        .all()
    )
    assert missing_process == []

    counts = await _relationship_type_counts(db_session, connection.id)
    assert counts["runs_process"] == 1


@pytest.mark.asyncio
async def test_extract_metadata_stores_qualified_hierarchy_names(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    await extract_metadata(db_session, connection.id, org.id)

    hierarchies = (
        (
            await db_session.execute(
                select(TM1Object).where(
                    TM1Object.connection_id == connection.id,
                    TM1Object.object_type == "hierarchy",
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(h.name for h in hierarchies) == [
        "Account:Account",
        "Product:Product",
        "Product:Product Alt",
        "Region:Region",
    ]


@pytest.mark.asyncio
async def test_extract_metadata_replaces_rather_than_duplicates(
    db_session, tm1_credentials_key, fake_tm1_client
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    await extract_metadata(db_session, connection.id, org.id)
    summary = await extract_metadata(db_session, connection.id, org.id)

    assert summary.objects_created == 11
    assert summary.relationships_created == 12

    objects = (
        (
            await db_session.execute(
                select(TM1Object).where(TM1Object.connection_id == connection.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(objects) == 11
