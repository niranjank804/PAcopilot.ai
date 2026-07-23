import pytest

from src.tm1.service import tm1_integration_service


@pytest.mark.asyncio
async def test_list_security_groups_returns_real_group_names(
    db_session, live_connection
):
    org, user, connection = live_connection

    groups = await tm1_integration_service.list_security_groups(
        db_session, connection.id, org.id
    )

    assert isinstance(groups, list)
    assert all(isinstance(name, str) for name in groups)


@pytest.mark.asyncio
async def test_get_security_group_returns_real_shape(db_session, live_connection):
    org, user, connection = live_connection

    groups = await tm1_integration_service.list_security_groups(
        db_session, connection.id, org.id
    )

    if not groups:
        pytest.skip("No security groups in this model to validate against.")

    group = await tm1_integration_service.get_security_group(
        db_session, connection.id, org.id, groups[0]
    )

    assert group.name == groups[0]
    assert isinstance(group.member_user_names, list)
    assert all(isinstance(name, str) for name in group.member_user_names)
