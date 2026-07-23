from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
from src.tm1.metadata.dependency_analyzer import (
    dependency_path,
    find_dependencies,
    find_dependents,
    find_unused_objects,
    get_cube_dependencies,
    get_dimension_dependents,
)
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


async def _seed_graph(db_session, connection_id, organization_id):
    now = datetime.now(timezone.utc)

    cube = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection_id,
            organization_id=organization_id,
            object_type="cube",
            name="Sales",
            extracted_at=now,
        ),
    )
    region = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection_id,
            organization_id=organization_id,
            object_type="dimension",
            name="Region",
            extracted_at=now,
        ),
    )
    product = await tm1_object_repository.create(
        db_session,
        TM1Object(
            connection_id=connection_id,
            organization_id=organization_id,
            object_type="dimension",
            name="Product",
            extracted_at=now,
        ),
    )

    for dimension in (region, product):
        await tm1_relationship_repository.create(
            db_session,
            TM1Relationship(
                connection_id=connection_id,
                organization_id=organization_id,
                from_object_id=cube.id,
                to_object_id=dimension.id,
                relationship_type="uses_dimension",
                extracted_at=now,
            ),
        )


async def _add_relationship(
    db_session, connection_id, organization_id, from_object, to_object, relationship_type
):
    now = datetime.now(timezone.utc)

    return await tm1_relationship_repository.create(
        db_session,
        TM1Relationship(
            connection_id=connection_id,
            organization_id=organization_id,
            from_object_id=from_object.id,
            to_object_id=to_object.id,
            relationship_type=relationship_type,
            extracted_at=now,
        ),
    )


async def _seed_multihop_graph(db_session, connection_id, organization_id):
    """chore -runs_process-> process -updates_cube-> Sales -uses_dimension->
    Region, with a Sales<->Expense references_cube cycle (to prove BFS
    terminates) and an isolated Orphan dimension (for find_unused_objects)."""

    now = datetime.now(timezone.utc)

    async def _make(object_type, name):
        return await tm1_object_repository.create(
            db_session,
            TM1Object(
                connection_id=connection_id,
                organization_id=organization_id,
                object_type=object_type,
                name=name,
                extracted_at=now,
            ),
        )

    chore = await _make("chore", "Nightly")
    process = await _make("process", "LoadSales")
    sales = await _make("cube", "Sales")
    expense = await _make("cube", "Expense")
    region = await _make("dimension", "Region")
    orphan = await _make("dimension", "Orphan")

    await _add_relationship(
        db_session, connection_id, organization_id, chore, process, "runs_process"
    )
    await _add_relationship(
        db_session, connection_id, organization_id, process, sales, "updates_cube"
    )
    await _add_relationship(
        db_session, connection_id, organization_id, sales, region, "uses_dimension"
    )
    await _add_relationship(
        db_session, connection_id, organization_id, sales, expense, "references_cube"
    )
    await _add_relationship(
        db_session, connection_id, organization_id, expense, sales, "references_cube"
    )

    return {
        "chore": chore,
        "process": process,
        "sales": sales,
        "expense": expense,
        "region": region,
        "orphan": orphan,
    }


@pytest.mark.asyncio
async def test_get_cube_dependencies_returns_dimensions(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_graph(db_session, connection.id, org.id)

    dimensions = await get_cube_dependencies(
        db_session, connection.id, org.id, "Sales"
    )

    assert set(dimensions) == {"Region", "Product"}


@pytest.mark.asyncio
async def test_get_dimension_dependents_returns_cubes(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_graph(db_session, connection.id, org.id)

    cubes = await get_dimension_dependents(db_session, connection.id, org.id, "Region")

    assert cubes == ["Sales"]


@pytest.mark.asyncio
async def test_get_cube_dependencies_raises_not_found_for_unknown_cube(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    with pytest.raises(NotFoundException):
        await get_cube_dependencies(db_session, connection.id, org.id, "Missing")


@pytest.mark.asyncio
async def test_get_dimension_dependents_raises_not_found_for_unknown_dimension(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)

    with pytest.raises(NotFoundException):
        await get_dimension_dependents(db_session, connection.id, org.id, "Missing")


@pytest.mark.asyncio
async def test_find_dependents_walks_multiple_hops(db_session, tm1_credentials_key):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    dependents = await find_dependents(db_session, connection.id, org.id, "cube", "Sales")

    names_by_type = {(d["object_type"], d["name"]) for d in dependents}
    assert ("process", "LoadSales") in names_by_type
    assert ("cube", "Expense") in names_by_type
    assert ("chore", "Nightly") in names_by_type


@pytest.mark.asyncio
async def test_find_dependents_does_not_hang_on_cycle(db_session, tm1_credentials_key):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    # Sales <-> Expense is a references_cube cycle; without cycle-safety
    # this would loop forever instead of returning.
    dependents = await find_dependents(db_session, connection.id, org.id, "cube", "Sales")

    sales_entries = [d for d in dependents if d["object_type"] == "cube" and d["name"] == "Sales"]
    assert sales_entries == []


@pytest.mark.asyncio
async def test_find_dependents_respects_max_depth(db_session, tm1_credentials_key):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    dependents = await find_dependents(
        db_session, connection.id, org.id, "cube", "Sales", max_depth=1
    )

    names = {(d["object_type"], d["name"]) for d in dependents}
    assert ("process", "LoadSales") in names
    assert ("chore", "Nightly") not in names


@pytest.mark.asyncio
async def test_find_dependencies_shows_everything_downstream(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    dependencies = await find_dependencies(
        db_session, connection.id, org.id, "process", "LoadSales"
    )

    names = {(d["object_type"], d["name"]) for d in dependencies}
    assert ("cube", "Sales") in names
    assert ("dimension", "Region") in names
    assert ("cube", "Expense") in names


@pytest.mark.asyncio
async def test_dependency_path_finds_a_route(db_session, tm1_credentials_key):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    path = await dependency_path(
        db_session, connection.id, org.id, "process", "LoadSales", "dimension", "Region"
    )

    assert path is not None
    assert [(p["object_type"], p["name"]) for p in path] == [
        ("process", "LoadSales"),
        ("cube", "Sales"),
        ("dimension", "Region"),
    ]


@pytest.mark.asyncio
async def test_dependency_path_returns_none_when_unreachable(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    path = await dependency_path(
        db_session, connection.id, org.id, "dimension", "Region", "process", "LoadSales"
    )

    assert path is None


@pytest.mark.asyncio
async def test_find_unused_objects_returns_only_isolated_objects(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    unused = await find_unused_objects(db_session, connection.id, org.id)

    assert unused == [{"object_type": "dimension", "name": "Orphan"}]


@pytest.mark.asyncio
async def test_find_unused_objects_filters_by_type(db_session, tm1_credentials_key):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    connection = await _create_connection(db_session, org.id, user.id)
    await _seed_multihop_graph(db_session, connection.id, org.id)

    unused_cubes = await find_unused_objects(
        db_session, connection.id, org.id, object_type="cube"
    )

    assert unused_cubes == []
