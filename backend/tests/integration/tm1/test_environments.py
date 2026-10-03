"""DEV / QA / PROD governance (phase 6), through the real API.

The rules (src/tm1/governance.py): each environment needs its own deploy
right; production needs a second person; the assistant cannot draft on
production; and a connection cannot be taken out of PROD without the
production right.
"""

import json

import pytest
from sqlalchemy import select

from src.ai.tools.tm1.changes import ProposeRuleUpdateTool
from src.core.exceptions import PermissionDeniedException
from src.database.models.permission import Permission
from src.database.models.role import Role
from src.database.models.role_permission import RolePermission
from src.database.models.user_role import UserRole
from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.integration.tm1.test_changes_api import (  # noqa: F401 - fixtures
    fake_tm1_client,
    tm1_credentials_key,
)


async def _connection(client, headers, environment="dev"):
    resp = await client.post(
        "/tm1/connections",
        json={
            "name": f"{environment.upper()} server",
            "address": "tm1.example.com",
            "port": 8010,
            "ssl": True,
            "username": "admin",
            "password": "secret",
            "environment": environment,
            # Team servers: approvers other than the creator must use them.
            "visibility": "organization",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["environment"] == environment
    return resp.json()["data"]["id"]


async def _draft(client, headers, connection_id):
    resp = await client.post(
        f"/tm1/connections/{connection_id}/changes",
        json={"change_type": "update_rules", "target_name": "Sales", "new_content": {"rules": "['A'] = N: 2;"}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def _user_with(db_session, org_id, *codes):
    """A member whose only rights are `codes` (plus reading TM1)."""

    user = await create_user(db_session, org_id)
    role = Role(organization_id=org_id, name=f"r-{user.id.hex[:8]}", is_system=False)
    db_session.add(role)
    await db_session.flush()
    for code in ("tm1.read", "tm1.write", *codes):
        permission = (await db_session.execute(select(Permission).where(Permission.code == code))).scalar_one()
        db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.flush()
    return user


async def _execute(client, headers, connection_id, change_id):
    return await client.post(
        f"/tm1/connections/{connection_id}/changes/{change_id}/execute", headers=headers
    )


@pytest.mark.asyncio
async def test_existing_and_new_connections_are_dev_by_default(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    resp = await client.post(
        "/tm1/connections",
        json={"name": "x", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "a", "password": "b"},
        headers=auth_headers(admin),
    )

    assert resp.json()["data"]["environment"] == "dev"


@pytest.mark.asyncio
async def test_qa_needs_the_qa_deploy_right(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    qa = await _connection(client, auth_headers(admin), "qa")
    change = await _draft(client, auth_headers(admin), qa)

    developer = await _user_with(db_session, org_id, "tm1.deploy")
    refused = await _execute(client, auth_headers(developer), qa, change)
    assert refused.status_code == 403
    assert "tm1.deploy.qa" in refused.text

    senior = await _user_with(db_session, org_id, "tm1.deploy", "tm1.deploy.qa")
    applied = await _execute(client, auth_headers(senior), qa, change)
    assert applied.status_code == 200, applied.text


@pytest.mark.asyncio
async def test_production_needs_a_second_person(client, db_session, tm1_credentials_key, fake_tm1_client):
    org, requester = await create_org_admin(db_session)
    org_id = org.id
    requester_headers = auth_headers(requester)
    prod = await _connection(client, requester_headers, "prod")
    change = await _draft(client, requester_headers, prod)

    own = await _execute(client, requester_headers, prod, change)
    assert own.status_code == 403
    assert "someone other than the person who requested it" in own.text

    approver = await create_user(db_session, org_id)
    await grant_system_role(db_session, approver.id, "Organization Admin")
    approved = await _execute(client, auth_headers(approver), prod, change)
    assert approved.status_code == 200, approved.text

    # Undoing a bad production change does not wait for a second person.
    rolled_back = await client.post(
        f"/tm1/connections/{prod}/changes/{change}/rollback", headers=requester_headers
    )
    assert rolled_back.status_code == 200, rolled_back.text


@pytest.mark.asyncio
async def test_the_assistant_cannot_draft_on_production(db_session, client, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    prod = await _connection(client, auth_headers(admin), "prod")
    db_session.info.pop("organization_id", None)

    with pytest.raises(PermissionDeniedException, match="read-only"):
        await ProposeRuleUpdateTool().execute(
            db_session, organization_id=org_id, user_id=admin.id,
            connection_id=prod, cube_name="Sales", rules="['A'] = N: 2;",
        )


@pytest.mark.asyncio
async def test_the_assistant_can_still_draft_on_dev(db_session, client, tm1_credentials_key, fake_tm1_client):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    dev = await _connection(client, auth_headers(admin), "dev")
    db_session.info.pop("organization_id", None)

    result = json.loads(await ProposeRuleUpdateTool().execute(
        db_session, organization_id=org_id, user_id=admin.id,
        connection_id=dev, cube_name="Sales", rules="['A'] = N: 2;",
    ))

    assert result["status"] == "draft"


@pytest.mark.asyncio
async def test_taking_a_connection_out_of_prod_needs_the_prod_right(
    client, db_session, tm1_credentials_key
):
    org, admin = await create_org_admin(db_session)
    org_id = org.id
    admin_headers = auth_headers(admin)
    prod = await _connection(client, admin_headers, "prod")

    writer = await _user_with(db_session, org_id, "tm1.deploy")
    refused = await client.patch(
        f"/tm1/connections/{prod}", json={"environment": "dev"}, headers=auth_headers(writer)
    )
    assert refused.status_code == 403

    allowed = await client.patch(
        f"/tm1/connections/{prod}", json={"environment": "qa"}, headers=admin_headers
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["environment"] == "qa"
