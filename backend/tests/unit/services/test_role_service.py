import pytest

from src.core.exceptions import NotFoundException, PermissionDeniedException
from src.repositories.role_repository import role_repository
from src.services.role_service import role_service
from tests.fixtures.factories import create_organization, create_user, grant_system_role


@pytest.mark.asyncio
async def test_cross_org_role_read_raises_not_found(db_session):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)

    role_a = await role_service.create_role(db_session, org_a.id, "A's Role")

    with pytest.raises(NotFoundException):
        await role_service.get_role(db_session, role_a.id, org_b.id)

    # owner can still read it
    fetched = await role_service.get_role(db_session, role_a.id, org_a.id)
    assert fetched.id == role_a.id


@pytest.mark.asyncio
async def test_cross_org_role_delete_raises_not_found(db_session):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)

    role_a = await role_service.create_role(db_session, org_a.id, "A's Role")

    with pytest.raises(NotFoundException):
        await role_service.delete_role(db_session, role_a.id, org_b.id)


@pytest.mark.asyncio
async def test_list_roles_includes_own_and_system_roles(db_session):
    org_a = await create_organization(db_session)
    role_a = await role_service.create_role(db_session, org_a.id, "A's Role")

    visible = await role_service.list_roles(db_session, org_a.id)
    names = {r.name for r in visible}

    assert role_a.name in names
    assert "Viewer" in names


@pytest.mark.asyncio
async def test_cannot_assign_cross_org_role(db_session):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    user_b = await create_user(db_session, org_b.id)

    role_a = await role_service.create_role(db_session, org_a.id, "A's Role")

    with pytest.raises(PermissionDeniedException):
        await role_service.assign_role(db_session, user_b.id, role_a.id, org_b.id)


@pytest.mark.asyncio
async def test_cannot_assign_role_to_user_outside_caller_org(db_session):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    user_b = await create_user(db_session, org_b.id)

    viewer = await role_repository.get_system_role(db_session, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await role_service.assign_role(db_session, user_b.id, viewer.id, org_a.id)


@pytest.mark.asyncio
async def test_cannot_mutate_system_role(db_session):
    org_a = await create_organization(db_session)
    viewer = await role_repository.get_system_role(db_session, "Viewer")

    with pytest.raises(PermissionDeniedException):
        await role_service.update_role(db_session, viewer.id, org_a.id, name="Hacked")

    with pytest.raises(PermissionDeniedException):
        await role_service.delete_role(db_session, viewer.id, org_a.id)


@pytest.mark.asyncio
async def test_can_assign_system_role_to_own_user(db_session):
    org_a = await create_organization(db_session)
    user_a = await create_user(db_session, org_a.id)
    viewer = await role_repository.get_system_role(db_session, "Viewer")

    assigned = await role_service.assign_role(db_session, user_a.id, viewer.id, org_a.id)
    assert assigned.role_id == viewer.id


@pytest.mark.asyncio
async def test_org_admin_has_roles_write_permission(db_session):
    from src.repositories.auth_repository import auth_repository

    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    await grant_system_role(db_session, user.id, "Organization Admin")

    has_perm = await auth_repository.user_has_permission(db_session, user.id, "roles.write")
    assert has_perm is True
