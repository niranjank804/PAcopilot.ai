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


# --- Address normalisation and the SaaS-type guard -------------------------
#
# Reproduces a real failure: a PA SaaS hostname pasted from the browser bar
# (trailing slash included) was saved as a *native* connection on port 8010.
# That combination can never connect, and the only feedback was a generic
# "check address, port, and credentials" toast.


@pytest.mark.asyncio
async def test_saas_host_saved_as_native_is_rejected_with_guidance(
    db_session, tm1_credentials_key
):
    from src.core.exceptions import ValidationException

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    with pytest.raises(ValidationException, match="Planning Analytics as a Service"):
        await tm1_integration_service.create_connection(
            db_session,
            organization_id=org.id,
            created_by=user.id,
            name="fpa",
            address="us-east-1.planninganalytics.saas.ibm.com/",
            port=8010,
            ssl=True,
            username="apikey",
            password="key",
        )


@pytest.mark.asyncio
async def test_pasted_url_is_stored_as_a_bare_hostname(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="SaaS",
        address="  https://us-east-1.planninganalytics.saas.ibm.com/  ",
        port=443,
        ssl=True,
        username="apikey",
        password="key",
        authentication_type="v12_saas",
        tenant="TENANT123",
        database="fpa",
    )

    assert connection.address == "us-east-1.planninganalytics.saas.ibm.com"


@pytest.mark.asyncio
async def test_full_rest_url_supplies_tenant_and_database(
    db_session, tm1_credentials_key
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="SaaS",
        address=(
            "https://us-east-1.planninganalytics.saas.ibm.com"
            "/api/TENANT123/v0/tm1/fpa/api/v1/Cubes"
        ),
        port=443,
        ssl=True,
        username="apikey",
        password="key",
        authentication_type="v12_saas",
    )

    assert connection.address == "us-east-1.planninganalytics.saas.ibm.com"
    assert connection.tenant == "TENANT123"
    assert connection.database == "fpa"


@pytest.mark.asyncio
async def test_misconfigured_connection_can_be_repaired_by_editing(
    db_session, tm1_credentials_key
):
    from src.core.exceptions import ValidationException
    from src.tm1.crypto import encrypt_password
    from src.database.models.tm1_connection import TM1Connection

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    # Saved before the guard existed, exactly as it appeared in production.
    broken = TM1Connection(
        organization_id=org.id,
        created_by=user.id,
        name="fpa",
        address="us-east-1.planninganalytics.saas.ibm.com/",
        port=8010,
        ssl=True,
        username="apikey",
        encrypted_password=encrypt_password("key"),
        authentication_type="native",
    )
    db_session.add(broken)
    await db_session.flush()

    # A rename alone leaves it unconnectable, so it is refused with the fix.
    with pytest.raises(ValidationException, match="Planning Analytics as a Service"):
        await tm1_integration_service.update_connection(
            db_session, broken.id, org.id, name="fpa-renamed"
        )

    repaired = await tm1_integration_service.update_connection(
        db_session,
        broken.id,
        org.id,
        address="us-east-1.planninganalytics.saas.ibm.com/",
        authentication_type="v12_saas",
        tenant="TENANT123",
        database="fpa",
    )

    assert repaired.address == "us-east-1.planninganalytics.saas.ibm.com"
    assert repaired.authentication_type == "v12_saas"
    assert repaired.tenant == "TENANT123"


# --- Saying *why* a connection failed ---------------------------------------


@pytest.mark.parametrize(
    ("error", "problem", "hint"),
    [
        ("auth", "credentials_rejected", "tenant ID"),
        ("not_found", "not_found", "database 'fpa' was not found"),
        ("unreachable", "unreachable", "Could not reach"),
    ],
)
@pytest.mark.asyncio
async def test_diagnose_connection_names_the_part_that_is_wrong(
    db_session, tm1_credentials_key, monkeypatch, error, problem, hint
):
    from src.tm1.exceptions import TM1AuthenticationError, TM1NotFoundError

    raised = {
        "auth": TM1AuthenticationError("401"),
        "not_found": TM1NotFoundError("404"),
        "unreachable": TM1ConnectionError("timeout"),
    }[error]

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="fpa",
        address="us-east-1.planninganalytics.saas.ibm.com",
        port=443,
        ssl=True,
        username="apikey",
        password="key",
        authentication_type="v12_saas",
        tenant="TENANT123",
        database="fpa",
    )

    monkeypatch.setattr(
        tm1_connection_manager, "get_client", AsyncMock(side_effect=raised)
    )

    diagnosis = await tm1_integration_service.diagnose_connection(
        db_session, connection.id, org.id
    )

    assert diagnosis.connected is False
    assert diagnosis.problem == problem
    assert hint in diagnosis.message
