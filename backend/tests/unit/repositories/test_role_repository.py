import pytest

from src.database.models.role import Role
from src.repositories.role_repository import role_repository
from tests.fixtures.factories import create_organization


@pytest.mark.asyncio
async def test_get_by_name_scoped_to_organization(db_session):
    org = await create_organization(db_session)

    role = await role_repository.create(
        db_session,
        Role(organization_id=org.id, name="Custom Role", description=None),
    )

    found = await role_repository.get_by_name(db_session, org.id, "Custom Role")
    assert found is not None
    assert found.id == role.id

    not_found = await role_repository.get_by_name(db_session, org.id, "Nonexistent")
    assert not_found is None


@pytest.mark.asyncio
async def test_list_visible_to_organization_includes_system_roles(db_session):
    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)

    role_a = await role_repository.create(
        db_session,
        Role(organization_id=org_a.id, name="Org A Role", description=None),
    )
    await role_repository.create(
        db_session,
        Role(organization_id=org_b.id, name="Org B Role", description=None),
    )

    visible = await role_repository.list_visible_to_organization(db_session, org_a.id)
    names = {r.name for r in visible}

    assert role_a.name in names
    assert "Org B Role" not in names
    # system roles (organization_id IS NULL) must be visible too
    assert any(r.organization_id is None for r in visible)
