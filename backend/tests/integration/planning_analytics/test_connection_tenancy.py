"""Tenant isolation for Planning Analytics connections.

Phase 1.6 implemented the authorization gate but could not prove it:
with nothing persisted, "organization A cannot reach organization B's
connection" was an assertion about code that never ran. These tests are
what make it a verified property.
"""

import uuid

import pytest
from cryptography.fernet import Fernet

import src.tm1.crypto as crypto_module
from src.core.config import settings
from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.planning_analytics.capabilities import ConnectionHealth
from src.planning_analytics.connection_service import connection_service
from tests.fixtures.factories import create_org_admin


@pytest.fixture
def credentials_key():
    original = settings.TM1_CREDENTIALS_KEY
    settings.TM1_CREDENTIALS_KEY = Fernet.generate_key().decode()
    crypto_module._fernet = None

    yield

    settings.TM1_CREDENTIALS_KEY = original
    crypto_module._fernet = None


async def _make_connection(db, org, user, name="Production", **kwargs):
    return await connection_service.create(
        db,
        organization_id=org.id,
        user_id=user.id,
        name=name,
        provider_type=kwargs.pop("provider_type", "tm1_rest"),
        **kwargs,
    )


class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_another_organizations_connection_is_not_found(
        self, db_session
    ):
        org_a, user_a = await create_org_admin(db_session)
        org_b, user_b = await create_org_admin(db_session)

        connection_b = await _make_connection(db_session, org_b, user_b)

        # Organization A holds the exact id.
        with pytest.raises(NotFoundException):
            await connection_service.get(
                db_session, connection_b.id, org_a.id
            )

    @pytest.mark.asyncio
    async def test_listing_never_crosses_tenants(self, db_session):
        org_a, user_a = await create_org_admin(db_session)
        org_b, user_b = await create_org_admin(db_session)

        await _make_connection(db_session, org_a, user_a, name="A-only")
        await _make_connection(db_session, org_b, user_b, name="B-only")

        listed_a = await connection_service.list_connections(db_session, org_a.id)
        names_a = {connection.name for connection in listed_a}

        assert names_a == {"A-only"}
        assert "B-only" not in names_a

    @pytest.mark.asyncio
    async def test_deleting_another_organizations_connection_is_refused(
        self, db_session
    ):
        org_a, _ = await create_org_admin(db_session)
        org_b, user_b = await create_org_admin(db_session)

        connection_b = await _make_connection(db_session, org_b, user_b)

        with pytest.raises(NotFoundException):
            await connection_service.delete(
                db_session, connection_b.id, org_a.id
            )

        # Still there, untouched.
        survivor = await connection_service.get(
            db_session, connection_b.id, org_b.id
        )

        assert survivor.id == connection_b.id

    @pytest.mark.asyncio
    async def test_a_random_id_is_not_found(self, db_session):
        org_a, _ = await create_org_admin(db_session)

        with pytest.raises(NotFoundException):
            await connection_service.get(db_session, uuid.uuid4(), org_a.id)

    @pytest.mark.asyncio
    async def test_the_same_name_is_allowed_in_different_organizations(
        self, db_session
    ):
        org_a, user_a = await create_org_admin(db_session)
        org_b, user_b = await create_org_admin(db_session)

        await _make_connection(db_session, org_a, user_a, name="Production")
        # Must not collide — a global unique name would leak the
        # existence of another tenant's connection via the constraint.
        second = await _make_connection(
            db_session, org_b, user_b, name="Production"
        )

        assert second.name == "Production"

    @pytest.mark.asyncio
    async def test_duplicate_name_within_one_organization_is_refused(
        self, db_session
    ):
        org, user = await create_org_admin(db_session)

        await _make_connection(db_session, org, user, name="Production")

        with pytest.raises(ConflictException):
            await _make_connection(db_session, org, user, name="Production")


class TestCredentialHandling:

    @pytest.mark.asyncio
    async def test_the_credential_is_encrypted_at_rest(
        self, db_session, credentials_key
    ):
        org, user = await create_org_admin(db_session)

        connection = await connection_service.create(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            name="MCP",
            provider_type="tm1_rest",
            authentication_type="oauth",
            credential="super-secret-oauth-token",
        )

        assert connection.encrypted_credential
        assert "super-secret-oauth-token" not in connection.encrypted_credential

    @pytest.mark.asyncio
    async def test_no_credential_means_no_ciphertext(self, db_session):
        org, user = await create_org_admin(db_session)

        connection = await _make_connection(db_session, org, user)

        assert connection.encrypted_credential is None


class TestProviderConfiguration:

    @pytest.mark.asyncio
    async def test_pax_cannot_be_configured_as_a_cloud_connection(
        self, db_session
    ):
        """PAx is COM-only; a cloud PAx connection could never connect.

        Enforced in code rather than only documented, so it cannot be
        configured by mistake.
        """

        org, user = await create_org_admin(db_session)

        with pytest.raises(ValidationException) as exc_info:
            await _make_connection(
                db_session, org, user, provider_type="pax"
            )

        assert "PAx" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_an_unknown_provider_is_refused(self, db_session):
        org, user = await create_org_admin(db_session)

        with pytest.raises(ValidationException):
            await _make_connection(
                db_session, org, user, provider_type="not_a_provider"
            )

    @pytest.mark.asyncio
    async def test_mcp_requires_a_base_url(self, db_session):
        org, user = await create_org_admin(db_session)

        with pytest.raises(ValidationException):
            await _make_connection(
                db_session, org, user, provider_type="ibm_mcp"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/mcp",
            "http://127.0.0.1/mcp",
            "file:///etc/passwd",
            "http://10.0.0.1/mcp",
        ],
    )
    async def test_an_unsafe_mcp_url_is_refused_before_storage(
        self, db_session, url
    ):
        """SSRF validation happens before the row exists.

        Storing first and validating at connect time would leave an
        unsafe URL in the database for any later job that forgot to
        re-check.
        """

        org, user = await create_org_admin(db_session)

        with pytest.raises(ValidationException):
            await _make_connection(
                db_session,
                org,
                user,
                provider_type="ibm_mcp",
                base_url=url,
            )

        assert await connection_service.list_connections(db_session, org.id) == []


class TestHealthLifecycle:

    @pytest.mark.asyncio
    async def test_a_new_connection_is_never_enabled(self, db_session):
        org, user = await create_org_admin(db_session)

        connection = await _make_connection(db_session, org, user)

        # Usable only after a check actually succeeds.
        assert connection.enabled is False
        assert connection.status == ConnectionHealth.UNKNOWN.value
        assert connection.capabilities is None

    @pytest.mark.asyncio
    async def test_a_successful_check_enables_the_connection(self, db_session):
        org, user = await create_org_admin(db_session)
        connection = await _make_connection(db_session, org, user)

        updated = await connection_service.record_health(
            db_session,
            connection,
            health=ConnectionHealth.CONNECTED,
            provider_version="1.2.3",
            capabilities=["list_cubes"],
        )

        assert updated.enabled is True
        assert updated.last_health_check is not None

    @pytest.mark.asyncio
    async def test_a_failed_check_disables_it_again(self, db_session):
        org, user = await create_org_admin(db_session)
        connection = await _make_connection(db_session, org, user)

        await connection_service.record_health(
            db_session, connection, health=ConnectionHealth.CONNECTED
        )
        updated = await connection_service.record_health(
            db_session,
            connection,
            health=ConnectionHealth.AUTHENTICATION_FAILED,
            error_category="AUTHENTICATION",
            error_message_safe="credentials rejected",
        )

        # Derived from the result, so a failing connection cannot be
        # left enabled by an admin who did not re-check it.
        assert updated.enabled is False

    @pytest.mark.asyncio
    async def test_entitlement_failure_is_distinct_from_auth_failure(
        self, db_session
    ):
        org, user = await create_org_admin(db_session)
        connection = await _make_connection(db_session, org, user)

        updated = await connection_service.record_health(
            db_session,
            connection,
            health=ConnectionHealth.LICENSE_OR_ENTITLEMENT_REQUIRED,
            error_category="ENTITLEMENT",
        )

        assert updated.status == "LICENSE_OR_ENTITLEMENT_REQUIRED"
        assert updated.status != ConnectionHealth.AUTHENTICATION_FAILED.value

    @pytest.mark.asyncio
    async def test_a_long_error_message_is_truncated(self, db_session):
        org, user = await create_org_admin(db_session)
        connection = await _make_connection(db_session, org, user)

        updated = await connection_service.record_health(
            db_session,
            connection,
            health=ConnectionHealth.UNREACHABLE,
            error_message_safe="x" * 5000,
        )

        assert len(updated.last_error_message_safe) <= 500
