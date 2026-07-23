import pytest

from src.tm1.service import tm1_integration_service
from tests.fixtures.factories import create_organization, create_user


@pytest.mark.asyncio
async def test_test_connection_succeeds_with_real_credentials(
    db_session, live_connection
):
    org, user, connection = live_connection

    connected = await tm1_integration_service.test_connection(
        db_session, connection.id, org.id
    )

    assert connected is True


@pytest.mark.asyncio
async def test_test_connection_fails_with_wrong_password(
    db_session, live_credentials_key, live_tm1_config
):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)

    connection = await tm1_integration_service.create_connection(
        db_session,
        organization_id=org.id,
        created_by=user.id,
        name="Live Validation (bad password)",
        address=live_tm1_config["address"],
        port=live_tm1_config["port"],
        ssl=live_tm1_config["ssl"],
        username=live_tm1_config["username"],
        password="definitely-the-wrong-password",
    )

    connected = await tm1_integration_service.test_connection(
        db_session, connection.id, org.id
    )

    assert connected is False
