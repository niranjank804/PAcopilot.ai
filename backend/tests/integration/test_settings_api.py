"""Self-service profile and organization settings.

Closes QA finding F2, where both surfaces read "isn't available yet".

The security shape matters more than the feature: the subject of both
endpoints comes from the authenticated session, never from the request,
so there is no id a caller can substitute to edit somebody else.
"""

import pytest
from sqlalchemy import select

from src.database.models.audit_log import AuditLog
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


class TestProfileUpdate:

    @pytest.mark.asyncio
    async def test_a_user_can_rename_themselves(self, client, db_session):
        _, user = await create_org_admin(db_session)

        response = await client.patch(
            "/users/me",
            json={"first_name": "Niranjan", "last_name": "Patra"},
            headers=auth_headers(user),
        )

        assert response.status_code == 200

        data = response.json()["data"]

        assert data["first_name"] == "Niranjan"
        assert data["last_name"] == "Patra"

    @pytest.mark.asyncio
    async def test_it_needs_no_admin_permission(self, client, db_session):
        """A user owns their own name.

        The least-privileged role must be able to do this, or the
        feature is useless to most of the organization.
        """

        org, _ = await create_org_admin(db_session)
        viewer = await create_user(db_session, org.id)
        await grant_system_role(db_session, viewer.id, "Viewer")

        response = await client.patch(
            "/users/me",
            json={"first_name": "View", "last_name": "Only"},
            headers=auth_headers(viewer),
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_identity_fields_cannot_be_changed(self, client, db_session):
        """Email is how Google sign-in matches the account.

        Letting a user rewrite it would let them take over another
        identity or lock themselves out. Extra keys are ignored rather
        than applied.
        """

        _, user = await create_org_admin(db_session)
        original_email = user.email

        response = await client.patch(
            "/users/me",
            json={
                "first_name": "A",
                "last_name": "B",
                "email": "attacker@evil.example",
                "username": "root",
                "is_active": True,
                "registration_status": "approved",
            },
            headers=auth_headers(user),
        )

        assert response.status_code == 200
        assert response.json()["data"]["email"] == original_email

    @pytest.mark.asyncio
    async def test_a_user_cannot_edit_another_account(self, client, db_session):
        """There is no id to substitute — the subject is the session.

        This is the property that makes the endpoint safe without a
        permission check.
        """

        org, victim = await create_org_admin(db_session)
        attacker = await create_user(db_session, org.id)
        await grant_system_role(db_session, attacker.id, "Viewer")

        await client.patch(
            "/users/me",
            json={
                "first_name": "Hijacked",
                "last_name": "Name",
                "id": str(victim.id),
                "user_id": str(victim.id),
            },
            headers=auth_headers(attacker),
        )

        await db_session.refresh(victim)

        assert victim.first_name != "Hijacked"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"first_name": "", "last_name": "B"},
            {"first_name": "A", "last_name": ""},
            {"first_name": "A"},
            {"first_name": "x" * 200, "last_name": "B"},
        ],
    )
    async def test_invalid_names_are_refused(self, client, db_session, payload):
        _, user = await create_org_admin(db_session)

        response = await client.patch(
            "/users/me", json=payload, headers=auth_headers(user)
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_it_requires_authentication(self, client, db_session):
        response = await client.patch(
            "/users/me", json={"first_name": "A", "last_name": "B"}
        )

        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_the_change_is_audited(self, client, db_session):
        _, user = await create_org_admin(db_session)

        await client.patch(
            "/users/me",
            json={"first_name": "Audited", "last_name": "Change"},
            headers=auth_headers(user),
        )

        rows = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "USER_PROFILE_UPDATED")
        )
        entry = rows.scalars().first()

        assert entry is not None
        # Old values are kept so a rename is reversible from the trail.
        assert entry.old_values is not None
        assert entry.new_values["first_name"] == "Audited"


class TestOrganizationSettings:

    @pytest.mark.asyncio
    async def test_an_admin_can_read_their_organization(
        self, client, db_session
    ):
        org, admin = await create_org_admin(db_session)

        response = await client.get(
            "/users/organization", headers=auth_headers(admin)
        )

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(org.id)

    @pytest.mark.asyncio
    async def test_an_admin_can_rename_their_organization(
        self, client, db_session
    ):
        _, admin = await create_org_admin(db_session)

        response = await client.patch(
            "/users/organization",
            json={"name": "Acme Planning", "domain": "acme.example"},
            headers=auth_headers(admin),
        )

        assert response.status_code == 200

        data = response.json()["data"]

        assert data["name"] == "Acme Planning"
        assert data["domain"] == "acme.example"

    @pytest.mark.asyncio
    async def test_a_non_admin_cannot_change_it(self, client, db_session):
        org, _ = await create_org_admin(db_session)
        viewer = await create_user(db_session, org.id)
        await grant_system_role(db_session, viewer.id, "Viewer")

        response = await client.patch(
            "/users/organization",
            json={"name": "Renamed By Viewer"},
            headers=auth_headers(viewer),
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_the_code_cannot_be_changed(self, client, db_session):
        """`code` is a stable identifier referenced elsewhere.

        Renaming it silently would break those references, so it is not
        in the update schema at all.
        """

        org, admin = await create_org_admin(db_session)
        original_code = org.code

        response = await client.patch(
            "/users/organization",
            json={"name": "New Name", "code": "hijacked", "plan": "enterprise"},
            headers=auth_headers(admin),
        )

        assert response.status_code == 200
        assert response.json()["data"]["code"] == original_code

    @pytest.mark.asyncio
    async def test_one_organization_cannot_rename_another(
        self, client, db_session
    ):
        """No organization id is accepted — it comes from the session.

        An endpoint that took one would need its own ownership check,
        and that is the check that gets forgotten.
        """

        org_a, admin_a = await create_org_admin(db_session)
        org_b, _ = await create_org_admin(db_session)

        original_name = org_b.name

        await client.patch(
            "/users/organization",
            json={
                "name": "Taken Over",
                "id": str(org_b.id),
                "organization_id": str(org_b.id),
            },
            headers=auth_headers(admin_a),
        )

        await db_session.refresh(org_b)

        assert org_b.name == original_name

    @pytest.mark.asyncio
    async def test_an_empty_domain_is_stored_as_null(self, client, db_session):
        _, admin = await create_org_admin(db_session)

        response = await client.patch(
            "/users/organization",
            json={"name": "Acme", "domain": "   "},
            headers=auth_headers(admin),
        )

        assert response.json()["data"]["domain"] is None

    @pytest.mark.asyncio
    async def test_the_change_is_audited(self, client, db_session):
        _, admin = await create_org_admin(db_session)

        await client.patch(
            "/users/organization",
            json={"name": "Audited Org"},
            headers=auth_headers(admin),
        )

        rows = await db_session.execute(
            select(AuditLog).where(AuditLog.action == "ORGANIZATION_UPDATED")
        )

        assert rows.scalars().first() is not None
