from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.core.exceptions import NotFoundException
from src.tm1.client.connection_manager import tm1_connection_manager
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


@pytest.fixture
def fake_tm1_client(monkeypatch):
    client = MagicMock()
    client.cubes.get_all_names.return_value = ["Sales"]
    client.dimensions.get_all_names.return_value = ["Region"]
    client.server.get_server_name.return_value = "TM1_SERVER"

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(return_value=client),
    )

    return client


@pytest.mark.asyncio
async def test_create_and_get_connection_hides_password(
    db_session, tm1_credentials_key
):
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
        password="super-secret",
    )

    assert connection.encrypted_password != "super-secret"

    fetched = await tm1_integration_service.get_connection(
        db_session, connection.id, org.id
    )
    assert fetched.id == connection.id


@pytest.mark.asyncio
async def test_get_connection_cross_org_raises_not_found(
    db_session, tm1_credentials_key
):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    user_a = await create_user(db_session, org_a.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org_a.id,
        created_by=user_a.id,
        name="Prod",
        address="tm1.example.com",
        port=8010,
        ssl=True,
        username="admin",
        password="secret",
    )

    with pytest.raises(NotFoundException):
        await tm1_integration_service.get_connection(
            db_session, connection.id, org_b.id
        )


@pytest.mark.asyncio
async def test_list_cubes_delegates_to_cube_service(
    db_session, tm1_credentials_key, fake_tm1_client
):
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

    cubes = await tm1_integration_service.list_cubes(db_session, connection.id, org.id)

    assert cubes == ["Sales"]


@pytest.mark.asyncio
async def test_test_connection_returns_true_on_success(
    db_session, tm1_credentials_key, fake_tm1_client
):
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

    connected = await tm1_integration_service.test_connection(
        db_session, connection.id, org.id
    )

    assert connected is True


@pytest.mark.asyncio
async def test_test_connection_returns_false_on_failure(
    db_session, tm1_credentials_key, monkeypatch
):
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

    monkeypatch.setattr(
        tm1_connection_manager,
        "get_client",
        AsyncMock(side_effect=TM1ConnectionError("unreachable")),
    )

    connected = await tm1_integration_service.test_connection(
        db_session, connection.id, org.id
    )

    assert connected is False


@pytest.mark.asyncio
async def test_create_v12_saas_connection_requires_tenant_and_database(
    db_session, tm1_credentials_key
):
    from src.core.exceptions import ValidationException

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    with pytest.raises(ValidationException):
        await tm1_integration_service.create_connection(
            db_session,
            organization_id=org.id,
            created_by=user.id,
            name="SaaS missing fields",
            address="us-east-1.planninganalytics.saas.ibm.com",
            port=443,
            ssl=True,
            username="apikey",
            password="key",
            authentication_type="v12_saas",
        )


@pytest.mark.asyncio
async def test_create_v12_saas_connection_persists_auth_fields(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="PA SaaS Trial",
        address="us-east-1.planninganalytics.saas.ibm.com",
        port=443,
        ssl=True,
        username="apikey",
        password="key",
        authentication_type="v12_saas",
        tenant="TENANT123",
        database="MyDatabase",
    )

    assert connection.authentication_type == "v12_saas"
    assert connection.tenant == "TENANT123"
    assert connection.database == "MyDatabase"
