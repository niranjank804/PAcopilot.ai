"""Tests for the session-level org-scoping backstop (src/database/tenancy.py).

These deliberately run raw, unscoped queries (`select(Model)` with no
`.where(...)`) rather than going through a repository's own
`list_by_organization` method - the point is to prove the *structural*
backstop works on its own, independent of any repository-level filtering
that would otherwise mask whether the mechanism itself does anything.
"""

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.database.models.audit_log import AuditLog
from src.database.models.role import Role
from src.database.models.tm1_connection import TM1Connection
from src.repositories.audit_log_repository import audit_log_repository
from src.repositories.role_repository import role_repository
from src.repositories.tm1_connection_repository import tm1_connection_repository
from tests.fixtures.factories import create_organization, create_user


async def _create_connection(db, organization_id, name):
    creator = await create_user(db, organization_id)
    return await tm1_connection_repository.create(
        db,
        TM1Connection(
            organization_id=organization_id,
            created_by=creator.id,
            name=name,
            address="localhost",
            port=8010,
            ssl=True,
            username="admin",
            encrypted_password="enc",
        ),
    )


@pytest.mark.asyncio
async def test_enforcement_is_on_by_default(db_session):
    """The backstop must be active in a default deployment.

    It shipped inert so it could be verified against the whole suite
    first. That happened, and the default flipped. This test is what
    stops it silently reverting: a backstop that exists in the codebase
    but not in production protects nobody.
    """

    assert settings.TENANCY_ENFORCEMENT_ENABLED is True

    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    await _create_connection(db_session, org_a.id, "Org A Conn (default)")
    await _create_connection(db_session, org_b.id, "Org B Conn (default)")

    db_session.info["organization_id"] = org_a.id

    # An unscoped select — no .where() — still only returns this org's
    # rows, purely because of the session-level filter.
    result = await db_session.execute(select(TM1Connection))
    names = {c.name for c in result.scalars().all()}

    assert "Org A Conn (default)" in names
    assert "Org B Conn (default)" not in names


@pytest.mark.asyncio
async def test_flag_off_disables_filtering(db_session, monkeypatch):
    """The escape hatch still works.

    Kept because turning enforcement off is the supported way to
    diagnose a suspected over-filtering bug, and that path must not rot.
    """

    monkeypatch.setattr(settings, "TENANCY_ENFORCEMENT_ENABLED", False)

    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    await _create_connection(db_session, org_a.id, "Org A Conn (flag off)")
    await _create_connection(db_session, org_b.id, "Org B Conn (flag off)")

    db_session.info["organization_id"] = org_a.id

    result = await db_session.execute(select(TM1Connection))
    names = {c.name for c in result.scalars().all()}

    assert "Org A Conn (flag off)" in names
    assert "Org B Conn (flag off)" in names


@pytest.mark.asyncio
async def test_flag_on_filters_by_session_org(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TENANCY_ENFORCEMENT_ENABLED", True)

    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    await _create_connection(db_session, org_a.id, "Org A Conn (flag on)")
    await _create_connection(db_session, org_b.id, "Org B Conn (flag on)")

    db_session.info["organization_id"] = org_a.id

    result = await db_session.execute(select(TM1Connection))
    names = {c.name for c in result.scalars().all()}

    assert "Org A Conn (flag on)" in names
    assert "Org B Conn (flag on)" not in names


@pytest.mark.asyncio
async def test_role_nullable_org_still_visible_when_flag_on(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TENANCY_ENFORCEMENT_ENABLED", True)

    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)

    global_role = await role_repository.create(
        db_session,
        Role(organization_id=None, name="Global Role (tenancy test)", description=None, is_system=True),
    )
    org_a_role = await role_repository.create(
        db_session,
        Role(organization_id=org_a.id, name="Org A Role (tenancy test)", description=None),
    )
    await role_repository.create(
        db_session,
        Role(organization_id=org_b.id, name="Org B Role (tenancy test)", description=None),
    )

    db_session.info["organization_id"] = org_a.id

    result = await db_session.execute(select(Role))
    names = {r.name for r in result.scalars().all()}

    assert global_role.name in names  # nullable org, global -> stays visible
    assert org_a_role.name in names
    assert "Org B Role (tenancy test)" not in names


@pytest.mark.asyncio
async def test_audit_log_nullable_org_not_leaked_across_orgs(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TENANCY_ENFORCEMENT_ENABLED", True)

    org_a = await create_organization(db_session)

    deleted_org_log = await audit_log_repository.create(
        db_session,
        AuditLog(organization_id=None, action="test_action", entity="test_entity"),
    )
    org_a_log = await audit_log_repository.create(
        db_session,
        AuditLog(organization_id=org_a.id, action="test_action", entity="test_entity"),
    )

    db_session.info["organization_id"] = org_a.id

    result = await db_session.execute(select(AuditLog))
    ids = {a.id for a in result.scalars().all()}

    assert org_a_log.id in ids
    # Unlike Role, AuditLog is NOT __tenant_nullable__: a NULL org_id means
    # the owning org was hard-deleted, not "global" - it must never surface
    # from a live org's session.
    assert deleted_org_log.id not in ids

    # list_by_organization must keep working exactly as before too.
    listed = await audit_log_repository.list_by_organization(db_session, org_a.id)
    assert {a.id for a in listed} == {org_a_log.id}


@pytest.mark.asyncio
async def test_session_with_no_org_context_is_unfiltered(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TENANCY_ENFORCEMENT_ENABLED", True)

    org_a = await create_organization(db_session)
    org_b = await create_organization(db_session)
    await _create_connection(db_session, org_a.id, "Org A Conn (no context)")
    await _create_connection(db_session, org_b.id, "Org B Conn (no context)")

    # Deliberately not setting db_session.info["organization_id"] - this is
    # the shape of a background script/seed job's session.
    result = await db_session.execute(select(TM1Connection))
    names = {c.name for c in result.scalars().all()}

    assert "Org A Conn (no context)" in names
    assert "Org B Conn (no context)" in names
