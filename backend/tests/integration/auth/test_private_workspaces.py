"""Each sign-up is private: nobody sees another person's TM1 connections.

Sign-ups without a code used to share one organization, so every new
account saw the owner's on-premises server. Now each gets a workspace of
its own and administers it — which is why a workspace admin must not be
able to make themselves the platform's Super Admin, and why the Super
Admin approves sign-ups across workspaces.
"""

import uuid

import pytest

from src.repositories.role_repository import role_repository
from src.repositories.user_repository import user_repository
from tests.fixtures.factories import (
    DEFAULT_PASSWORD,
    auth_headers,
    create_org_admin,
    create_organization,
    create_user,
    grant_system_role,
)


async def _sign_up(client, db_session, suffix: str):
    # Through the service: the test then acts on the account directly.
    from src.schemas.auth import RegisterRequest
    from src.services.auth_service import auth_service

    # An earlier request in the same test stamps its caller's organization
    # on this shared session (src/database/tenancy.py); a sign-up has none.
    db_session.info.pop("organization_id", None)
    await auth_service.register(
        db_session,
        RegisterRequest(
            username=f"solo_{suffix}",
            email=f"solo_{suffix}@example.com",
            password=DEFAULT_PASSWORD,
            first_name="Solo",
            last_name="User",
        ),
    )
    return await user_repository.get_by_username(db_session, f"solo_{suffix}")


async def _super_admin(db_session):
    org = await create_organization(db_session)
    user = await create_user(db_session, org.id)
    await grant_system_role(db_session, user.id, "Super Admin")
    return user


@pytest.mark.asyncio
async def test_a_new_sign_up_cannot_see_anyone_elses_connections(client, db_session):
    # The owner's organization, with a TM1 connection in it.
    owner_org, owner = await create_org_admin(db_session)
    created = await client.post(
        "/tm1/connections",
        json={
            "name": "owners-server",
            "address": "tm1.owner.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
        },
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text

    newcomer = await _sign_up(client, db_session, uuid.uuid4().hex[:8])
    newcomer.registration_status = "approved"
    await user_repository.update(db_session, newcomer)

    assert newcomer.organization_id != owner_org.id
    listed = await client.get("/tm1/connections", headers=auth_headers(newcomer))
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []


@pytest.mark.asyncio
async def test_the_owner_of_a_workspace_administers_it(client, db_session):
    user = await _sign_up(client, db_session, uuid.uuid4().hex[:8])

    from src.repositories.user_role_repository import user_role_repository

    roles = await user_role_repository.role_names_by_user(db_session, [user.id])
    assert roles[user.id] == ["Organization Admin"]


@pytest.mark.asyncio
async def test_a_workspace_admin_cannot_make_themselves_super_admin(client, db_session):
    _org, admin = await create_org_admin(db_session)
    super_role = await role_repository.get_system_role(db_session, "Super Admin")

    resp = await client.post(
        f"/users/{admin.id}/roles",
        json={"role_id": str(super_role.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_the_super_admin_reviews_sign_ups_from_every_workspace(client, db_session):
    boss = await _super_admin(db_session)
    newcomer = await _sign_up(client, db_session, uuid.uuid4().hex[:8])

    listed = await client.get("/admin/signups", headers=auth_headers(boss))
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json()["data"] if r["id"] == str(newcomer.id))
    assert row["organization_name"].endswith("'s workspace")

    approved = await client.post(
        f"/admin/signups/{newcomer.id}/approve", headers=auth_headers(boss)
    )
    assert approved.status_code == 200, approved.text

    db_session.info.pop("organization_id", None)  # a fresh session in production
    login = await client.post(
        "/auth/login",
        json={"username": newcomer.username, "password": DEFAULT_PASSWORD},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_only_the_super_admin_reviews_sign_ups(client, db_session):
    _org, admin = await create_org_admin(db_session)

    resp = await client.get("/admin/signups", headers=auth_headers(admin))
    assert resp.status_code == 403
