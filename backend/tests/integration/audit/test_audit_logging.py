import pytest
from sqlalchemy import select

from src.database.models.audit_log import AuditLog
from tests.fixtures.factories import auth_headers, create_org_admin


@pytest.mark.asyncio
async def test_role_creation_writes_audit_log(client, db_session):
    org, admin = await create_org_admin(db_session)

    create_resp = await client.post(
        "/roles",
        json={"name": "Audited Role"},
        headers=auth_headers(admin),
    )
    role_id = create_resp.json()["data"]["id"]

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "Role",
            AuditLog.action == "create",
        )
    )
    logs = result.scalars().all()

    matching = [log for log in logs if str(log.entity_id) == role_id]
    assert len(matching) == 1
    assert matching[0].user_id == admin.id
    assert matching[0].organization_id == org.id
    assert matching[0].new_values["name"] == "Audited Role"


@pytest.mark.asyncio
async def test_role_deletion_writes_audit_log_with_old_values(client, db_session):
    org, admin = await create_org_admin(db_session)

    create_resp = await client.post(
        "/roles",
        json={"name": "Temp Role"},
        headers=auth_headers(admin),
    )
    role_id = create_resp.json()["data"]["id"]

    await client.delete(f"/roles/{role_id}", headers=auth_headers(admin))

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity == "Role",
            AuditLog.action == "delete",
        )
    )
    matching = [
        log for log in result.scalars().all() if str(log.entity_id) == role_id
    ]

    assert len(matching) == 1
    assert matching[0].old_values["name"] == "Temp Role"
