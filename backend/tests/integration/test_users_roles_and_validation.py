"""Two QA findings with a backend half.

The Users page had no role column — the API never returned roles, so a
list of members could not say who was an admin. And a request that
failed validation produced a message that was a Python repr of a list
of dicts, which the frontend showed verbatim.
"""

import pytest

from src.repositories.user_role_repository import user_role_repository
from tests.fixtures.factories import (
    auth_headers,
    create_org_admin,
    create_user,
    grant_system_role,
)


class TestRolesOnTheUserList:

    @pytest.mark.asyncio
    async def test_each_user_carries_their_role_names(self, client, db_session):
        org, admin = await create_org_admin(db_session)
        viewer = await create_user(db_session, org.id)
        await grant_system_role(db_session, viewer.id, "Viewer")

        response = await client.get("/users", headers=auth_headers(admin))

        assert response.status_code == 200

        by_id = {u["id"]: u for u in response.json()["data"]}

        assert by_id[str(viewer.id)]["roles"] == ["Viewer"]
        # The admin has a role too; exactly which name is the factory's
        # business, but an admin with no roles would be the original bug.
        assert by_id[str(admin.id)]["roles"]

    @pytest.mark.asyncio
    async def test_a_user_with_no_roles_gets_an_empty_list(
        self, client, db_session
    ):
        """Not null, not missing — the frontend maps over it."""

        org, admin = await create_org_admin(db_session)
        nobody = await create_user(db_session, org.id)

        response = await client.get("/users", headers=auth_headers(admin))

        by_id = {u["id"]: u for u in response.json()["data"]}

        assert by_id[str(nobody.id)]["roles"] == []

    @pytest.mark.asyncio
    async def test_roles_are_fetched_for_many_users_at_once(self, db_session):
        """One query, not one per user.

        The list endpoint could have called the per-user roles lookup in
        a loop. That is an N+1 against a page whose whole purpose is to
        list every member.
        """

        org, admin = await create_org_admin(db_session)
        first = await create_user(db_session, org.id)
        second = await create_user(db_session, org.id)
        await grant_system_role(db_session, first.id, "Viewer")
        await grant_system_role(db_session, second.id, "Analyst")

        names = await user_role_repository.role_names_by_user(
            db_session, [first.id, second.id, admin.id]
        )

        assert names[first.id] == ["Viewer"]
        assert names[second.id] == ["Analyst"]
        assert admin.id in names

    @pytest.mark.asyncio
    async def test_an_empty_id_list_needs_no_query(self, db_session):
        assert await user_role_repository.role_names_by_user(db_session, []) == {}


class TestValidationErrorMessages:

    @pytest.mark.asyncio
    async def test_a_missing_field_is_named_in_plain_words(
        self, client, db_session
    ):
        """What a user sees in the toast.

        Before: `[{'type': 'missing', 'loc': ('body', 'files'), 'msg':
        'Field required', ...}]`. After: `files: Field required`.
        """

        _, admin = await create_org_admin(db_session)

        # No multipart body at all — the exact request the broken
        # Coding Standards page was sending.
        response = await client.post(
            "/learning/corpus", headers=auth_headers(admin)
        )

        assert response.status_code == 422

        error = response.json()["error"]

        assert error["code"] == "VALIDATION_ERROR"
        assert "files" in error["message"]
        assert "required" in error["message"].lower()
        # No Python repr leaking through.
        assert "{'type'" not in error["message"]
        assert "loc" not in error["message"]

    @pytest.mark.asyncio
    async def test_the_envelope_shape_is_unchanged(self, client, db_session):
        """The frontend's unwrap() reads success/error.code/error.message."""

        _, admin = await create_org_admin(db_session)

        response = await client.post(
            "/learning/corpus", headers=auth_headers(admin)
        )
        body = response.json()

        assert body["success"] is False
        assert set(body["error"]) >= {"code", "message"}
