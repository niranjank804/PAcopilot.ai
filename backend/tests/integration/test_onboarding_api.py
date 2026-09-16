"""Onboarding state for the product tour.

The feature is small; the property that matters is the same one the
profile endpoint has. The subject is the session, so there is no id a
caller can substitute to mark somebody else as onboarded — or, more
usefully to an attacker, to reset a colleague's account into showing a
modal on their next login.
"""

import pytest

from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


class TestRecordingProgress:

    @pytest.mark.asyncio
    async def test_a_new_user_has_seen_nothing(self, client, db_session):
        """Null is what a first login looks like.

        The migration deliberately did not backfill existing rows: doing
        so would have marked everyone who signed up before the tour
        existed as having already completed it.
        """

        _, user = await create_org_admin(db_session)

        response = await client.get("/auth/me", headers=auth_headers(user))

        assert response.status_code == 200

        data = response.json()["data"]

        assert data["onboarding_completed_at"] is None
        assert data["onboarding_dismissed_at"] is None

    @pytest.mark.asyncio
    async def test_completing_it_is_recorded(self, client, db_session):
        _, user = await create_org_admin(db_session)

        response = await client.post(
            "/users/me/onboarding",
            json={"action": "completed"},
            headers=auth_headers(user),
        )

        assert response.status_code == 200
        assert response.json()["data"]["onboarding_completed_at"] is not None

    @pytest.mark.asyncio
    async def test_dismissing_it_is_distinct_from_completing_it(
        self, client, db_session
    ):
        """"Not now" and "done" permit different things next."""

        _, user = await create_org_admin(db_session)

        response = await client.post(
            "/users/me/onboarding",
            json={"action": "dismissed"},
            headers=auth_headers(user),
        )

        data = response.json()["data"]

        assert data["onboarding_dismissed_at"] is not None
        assert data["onboarding_completed_at"] is None

    @pytest.mark.asyncio
    async def test_restart_clears_both(self, client, db_session):
        """Help -> Take Product Tour, which must not delete anything else."""

        _, user = await create_org_admin(db_session)
        headers = auth_headers(user)

        await client.post(
            "/users/me/onboarding", json={"action": "completed"}, headers=headers
        )

        response = await client.post(
            "/users/me/onboarding", json={"action": "restart"}, headers=headers
        )

        data = response.json()["data"]

        assert data["onboarding_completed_at"] is None
        assert data["onboarding_dismissed_at"] is None
        # The account is otherwise untouched.
        assert data["username"] == user.username
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_completing_after_dismissing_clears_the_dismissal(
        self, client, db_session
    ):
        """Otherwise a user who said "later" and then finished would stay
        flagged as having postponed it."""

        _, user = await create_org_admin(db_session)
        headers = auth_headers(user)

        await client.post(
            "/users/me/onboarding", json={"action": "dismissed"}, headers=headers
        )
        response = await client.post(
            "/users/me/onboarding", json={"action": "completed"}, headers=headers
        )

        data = response.json()["data"]

        assert data["onboarding_completed_at"] is not None
        assert data["onboarding_dismissed_at"] is None


class TestItIsTheCallersOwnState:

    @pytest.mark.asyncio
    async def test_no_id_is_accepted_from_the_body(self, client, db_session):
        """The property that makes this safe without a permission check.

        Resetting a colleague's onboarding is not catastrophic, but it is
        somebody else's account — and an endpoint that took an id would
        need its own ownership check, which is the check that gets
        forgotten.
        """

        org, victim = await create_org_admin(db_session)
        attacker = await create_user(db_session, org.id)
        await grant_system_role(db_session, attacker.id, "Viewer")

        await client.post(
            "/users/me/onboarding",
            json={
                "action": "completed",
                "user_id": str(victim.id),
                "id": str(victim.id),
            },
            headers=auth_headers(attacker),
        )

        await db_session.refresh(victim)

        assert victim.onboarding_completed_at is None

    @pytest.mark.asyncio
    async def test_the_least_privileged_role_can_use_it(
        self, client, db_session
    ):
        """A Viewer still gets introduced to the product."""

        org, _ = await create_org_admin(db_session)
        viewer = await create_user(db_session, org.id)
        await grant_system_role(db_session, viewer.id, "Viewer")

        response = await client.post(
            "/users/me/onboarding",
            json={"action": "completed"},
            headers=auth_headers(viewer),
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_it_requires_authentication(self, client, db_session):
        response = await client.post(
            "/users/me/onboarding", json={"action": "completed"}
        )

        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_an_unknown_action_is_refused(self, client, db_session):
        """The action is a closed set, so a typo cannot silently do
        nothing and report success."""

        _, user = await create_org_admin(db_session)

        response = await client.post(
            "/users/me/onboarding",
            json={"action": "skipped-forever"},
            headers=auth_headers(user),
        )

        assert response.status_code == 422
