import json
import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.analysis import (
    DependencyPathTool,
    FindDependenciesTool,
    FindDependentsTool,
    FindUnusedObjectsTool,
)
from src.core.config import settings
from src.core.exceptions import PermissionDeniedException
from src.database.models.tm1_object import TM1Object
from src.database.models.tm1_relationship import TM1Relationship
from src.repositories.tm1_object_repository import tm1_object_repository
from src.repositories.tm1_relationship_repository import tm1_relationship_repository
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

    process = await _make("process", "LoadSales")
    sales = await _make("cube", "Sales")
    region = await _make("dimension", "Region")
    orphan = await _make("dimension", "Orphan")

    for from_obj, to_obj, relationship_type in (
        (process, sales, "updates_cube"),
        (sales, region, "uses_dimension"),
    ):
        await tm1_relationship_repository.create(
            db_session,
            TM1Relationship(
                connection_id=connection_id,
                organization_id=organization_id,
                from_object_id=from_obj.id,
                to_object_id=to_obj.id,
                relationship_type=relationship_type,
                extracted_at=now,
            ),
        )

    return {"process": process, "sales": sales, "region": region, "orphan": orphan}


@pytest.mark.asyncio
async def test_find_dependents_tool_returns_upstream_objects(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await FindDependentsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        object_type="cube",
        name="Sales",
    )

    body = json.loads(result)
    names = {(d["object_type"], d["name"]) for d in body["dependents"]}
    assert ("process", "LoadSales") in names


@pytest.mark.asyncio
async def test_find_dependencies_tool_returns_downstream_objects(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await FindDependenciesTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        object_type="process",
        name="LoadSales",
    )

    body = json.loads(result)
    names = {(d["object_type"], d["name"]) for d in body["dependencies"]}
    assert ("cube", "Sales") in names
    assert ("dimension", "Region") in names


@pytest.mark.asyncio
async def test_dependency_path_tool_finds_a_route(db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await DependencyPathTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        from_type="process",
        from_name="LoadSales",
        to_type="dimension",
        to_name="Region",
    )

    body = json.loads(result)
    assert body["found"] is True
    assert [(p["object_type"], p["name"]) for p in body["path"]] == [
        ("process", "LoadSales"),
        ("cube", "Sales"),
        ("dimension", "Region"),
    ]


@pytest.mark.asyncio
async def test_find_unused_objects_tool_returns_isolated_objects(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await FindUnusedObjectsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
    )

    body = json.loads(result)
    assert body["unused"] == [{"object_type": "dimension", "name": "Orphan"}]


@pytest.mark.asyncio
async def test_analysis_tools_raise_when_lacking_permission(db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await FindDependentsTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
            object_type="cube",
            name="Sales",
        )

    with pytest.raises(PermissionDeniedException):
        await FindUnusedObjectsTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
        )
