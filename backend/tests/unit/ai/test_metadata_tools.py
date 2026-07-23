import json
import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.ai.tools.tm1.metadata import (
    GetCubeDependenciesTool,
    GetDimensionDependentsTool,
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
    await tm1_relationship_repository.create(
        db_session,
        TM1Relationship(
            connection_id=connection_id,
            organization_id=organization_id,
            from_object_id=cube.id,
            to_object_id=region.id,
            relationship_type="uses_dimension",
            extracted_at=now,
        ),
    )


@pytest.mark.asyncio
async def test_get_cube_dependencies_tool_returns_dimensions(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await GetCubeDependenciesTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        cube_name="Sales",
    )

    assert json.loads(result) == {"cube": "Sales", "dimensions": ["Region"]}


@pytest.mark.asyncio
async def test_get_dimension_dependents_tool_returns_cubes(
    db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    connection = await _create_connection(db_session, org.id, admin.id)
    await _seed_graph(db_session, connection.id, org.id)

    result = await GetDimensionDependentsTool().execute(
        db_session,
        organization_id=org.id,
        user_id=admin.id,
        connection_id=str(connection.id),
        dimension_name="Region",
    )

    assert json.loads(result) == {"dimension": "Region", "cubes": ["Sales"]}


@pytest.mark.asyncio
async def test_get_cube_dependencies_tool_raises_when_lacking_permission(db_session):
    org = await create_organization(db_session)
    viewer = await create_user(db_session, org.id)
    await grant_system_role(db_session, viewer.id, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await GetCubeDependenciesTool().execute(
            db_session,
            organization_id=org.id,
            user_id=viewer.id,
            connection_id=str(uuid.uuid4()),
            cube_name="Sales",
        )
