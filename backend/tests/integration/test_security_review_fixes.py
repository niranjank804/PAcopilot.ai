"""Fixes from the security review (2026-10-06): relabelling a connection to
dodge its rules, re-pointing saved credentials, sharing someone's private
connection, stripping the Super Admin, undoing a platform deactivation,
and connecting to a private address through a public name."""

import uuid

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.database.models.audit_log import AuditLog
from src.database.models.tm1_connection import TM1Connection
from src.repositories.role_repository import role_repository
from src.tm1 import governance
from src.tm1.client import connection_manager as manager_module
from src.tm1.exceptions import TM1ConnectionError
from tests.fixtures.factories import auth_headers, create_org_admin, create_user, grant_system_role
from tests.integration.tm1.test_environments import _connection, _user_with
from tests.integration.tm1.test_changes_api import tm1_credentials_key  # noqa: F401 - fixture


@pytest.mark.asyncio
async def test_relabelling_qa_as_dev_needs_the_qa_right(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    qa = await _connection(client, auth_headers(admin), "qa")
    member = await _user_with(db_session, org.id, "tm1.deploy")
    headers = auth_headers(member)
    await db_session.commit()

    resp = await client.patch(f"/tm1/connections/{qa}", json={"environment": "dev"}, headers=headers)
    assert resp.status_code == 403, resp.text
    assert "tm1.deploy.qa" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_change_keeps_the_rules_of_the_environment_it_was_drafted_on():
    class Change:
        environment = "prod"

    class Connection:
        environment = "dev"

    assert governance.effective_environment(Change(), Connection()) == "prod"
    Change.environment = None
    assert governance.effective_environment(Change(), Connection()) == "dev"


@pytest.mark.asyncio
async def test_saved_credentials_are_never_sent_to_a_new_address(client, db_session, tm1_credentials_key):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    await db_session.commit()

    moved = await client.patch(f"/tm1/connections/{dev}", json={"address": "attacker.example.net"}, headers=headers)
    assert moved.status_code == 422, moved.text
    assert "Re-enter the password" in moved.json()["error"]["message"]

    same = await client.patch(f"/tm1/connections/{dev}", json={"address": "https://tm1.example.com", "name": "renamed"},
                              headers=headers)
    assert same.status_code == 200, same.text

    retyped = await client.patch(f"/tm1/connections/{dev}",
                                 json={"address": "tm1-new.example.com", "password": "new-secret"}, headers=headers)
    assert retyped.status_code == 200, retyped.text

    db_session.info.pop("organization_id", None)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "update_connection", AuditLog.entity_id == uuid.UUID(dev))
    )).scalars().all()
    # One transaction, one timestamp: pick the edit that changed the password.
    [row] = [r for r in rows if r.new_values.get("password_changed")]
    assert row.new_values["changed"]["address"] == {"from": "tm1.example.com", "to": "tm1-new.example.com"}
    assert row.new_values["password_changed"] is True
    assert "new-secret" not in repr(row.new_values)


@pytest.mark.asyncio
async def test_only_the_owner_shares_a_private_connection(client, db_session, tm1_credentials_key):
    org, admin = await create_org_admin(db_session)
    member = await _user_with(db_session, org.id)
    private = (await client.post(
        "/tm1/connections",
        json={"name": "mine", "address": "tm1.example.com", "port": 8010, "ssl": True,
              "username": "me", "password": "secret"},
        headers=auth_headers(member),
    )).json()["data"]["id"]
    headers = auth_headers(admin)
    await db_session.commit()

    resp = await client.patch(f"/tm1/connections/{private}", json={"visibility": "organization"}, headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_a_workspace_admin_cannot_strip_the_super_admin(client, db_session):
    org, admin = await create_org_admin(db_session)
    boss = await create_user(db_session, org.id)
    await grant_system_role(db_session, boss.id, "Super Admin")
    role = await role_repository.get_system_role(db_session, "Super Admin")
    headers = auth_headers(admin)
    await db_session.commit()

    resp = await client.delete(f"/users/{boss.id}/roles/{role.id}", headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_a_platform_deactivation_sticks(client, db_session):
    org, admin = await create_org_admin(db_session)
    boss_org, boss = await create_org_admin(db_session)
    await grant_system_role(db_session, boss.id, "Super Admin")
    person = await create_user(db_session, org.id)
    admin_headers, boss_headers = auth_headers(admin), auth_headers(boss)
    person_id = person.id
    await db_session.commit()

    assert (await client.post(f"/admin/platform/users/{person_id}/deactivate", json={"reason": "abuse"},
                              headers=boss_headers)).status_code == 200
    db_session.info.pop("organization_id", None)
    resp = await client.post(f"/users/{person_id}/activate", headers=admin_headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_a_public_name_for_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "TM1_ALLOW_PRIVATE_ADDRESSES", False)

    class Loop:
        async def getaddrinfo(self, host, port):
            return [(2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(manager_module.asyncio, "get_running_loop", lambda: Loop())
    connection = TM1Connection(id=uuid.uuid4(), address="127.0.0.1.nip.io", port=8010, ssl=True,
                               username="a", encrypted_password="x", authentication_type="native")

    with pytest.raises(TM1ConnectionError):
        await manager_module._refuse_private_destination(connection)


@pytest.mark.asyncio
async def test_a_password_reset_confirms_the_email(client, db_session, monkeypatch):
    from src.services.auth_service import auth_service

    _org, person = await create_org_admin(db_session)
    person.email_verified_at = None
    await db_session.flush()
    import hashlib
    import secrets
    from datetime import datetime, timedelta, timezone
    from src.database.models.password_reset_token import PasswordResetToken

    raw = secrets.token_urlsafe(32)
    db_session.add(PasswordResetToken(
        user_id=person.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    await db_session.flush()

    await auth_service.reset_password(db_session, raw, "A-new-password-123!")
    assert person.email_verified_at is not None


@pytest.mark.asyncio
async def test_database_details_are_for_the_platform_owner_only(client, db_session):
    _org, admin = await create_org_admin(db_session)
    resp = await client.get("/database/details", headers=auth_headers(admin))
    assert resp.status_code == 403, resp.text


def test_certificate_checking_follows_the_connection():
    from src.tm1.client.connection_manager import build_tm1_kwargs

    connection = TM1Connection(id=uuid.uuid4(), address="tm1.example.com", port=8010, ssl=True,
                               username="a", encrypted_password="x", authentication_type="native",
                               verify_ssl=True)
    assert build_tm1_kwargs(connection, "pw")["verify"] is True
    connection.verify_ssl = False
    assert build_tm1_kwargs(connection, "pw")["verify"] is False
    connection.ssl = False
    assert "verify" not in build_tm1_kwargs(connection, "pw")


@pytest.mark.asyncio
async def test_turning_certificate_checking_off_needs_the_password(client, db_session, tm1_credentials_key):
    _org, admin = await create_org_admin(db_session)
    headers = auth_headers(admin)
    dev = await _connection(client, headers, "dev")
    await db_session.commit()

    off = await client.patch(f"/tm1/connections/{dev}", json={"verify_ssl": False}, headers=headers)
    assert off.status_code == 422, off.text
    assert "certificate checking" in off.json()["error"]["message"]

    retyped = await client.patch(f"/tm1/connections/{dev}", json={"verify_ssl": False, "password": "again"},
                                 headers=headers)
    assert retyped.status_code == 200 and retyped.json()["data"]["verify_ssl"] is False
