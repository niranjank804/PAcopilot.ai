"""Connection lifecycle, with tenancy enforced at every entry point.

The rule: **no method here takes an organization id from a caller.** It
comes from the authenticated session and is applied as a filter, so a
forged connection id resolves to nothing rather than to someone else's
row. Cross-tenant access returns 404, matching the pattern used
throughout this codebase — a 403 would confirm the row exists.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ConflictException,
    NotFoundException,
    ValidationException,
)
from src.database.models.planning_analytics_connection import (
    PlanningAnalyticsConnection,
)
from src.planning_analytics.capabilities import ConnectionHealth, ProviderType
from src.planning_analytics.ssrf import validate_mcp_endpoint
from src.tm1.crypto import encrypt_password

#: PAx is absent on purpose. It is a COM interface obtained from a
#: running Excel process, with no network form, so a cloud-side "PAx
#: connection" could never connect to anything. Enforced here rather
#: than documented, so it cannot be configured by mistake.
CONFIGURABLE_PROVIDERS = frozenset(
    {
        ProviderType.TM1_REST,
        ProviderType.IBM_MCP,
        ProviderType.PAFE_WORKER,
    }
)

#: Providers whose base_url the backend will actually dial, and which
#: therefore must pass SSRF validation before being stored.
_URL_PROVIDERS = frozenset({ProviderType.IBM_MCP})

_MAX_ERROR_CHARS = 500


class ConnectionService:

    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        provider_type: str,
        base_url: str | None = None,
        server_name: str | None = None,
        environment_type: str | None = None,
        authentication_type: str = "none",
        credential: str | None = None,
        allow_private_networks: bool = False,
    ) -> PlanningAnalyticsConnection:

        name = (name or "").strip()

        if not name:
            raise ValidationException("A connection name is required.")

        try:
            provider = ProviderType(provider_type)
        except ValueError:
            raise ValidationException(f"Unknown provider type: {provider_type}")

        if provider not in CONFIGURABLE_PROVIDERS:
            raise ValidationException(
                f"'{provider.value}' cannot be configured as a connection. "
                "PAx is a client-side Excel automation API and is reached "
                "through the Windows worker, not as a cloud provider."
            )

        if provider in _URL_PROVIDERS:
            if not base_url:
                raise ValidationException(
                    f"A base URL is required for {provider.value}."
                )

            # Validated *before* storage, so an unsafe URL never reaches
            # the database and cannot be dialled by a later background
            # task that skipped the check.
            validate_mcp_endpoint(
                base_url, allow_private_networks=allow_private_networks
            )

        existing = await db.execute(
            select(PlanningAnalyticsConnection).where(
                PlanningAnalyticsConnection.organization_id == organization_id,
                PlanningAnalyticsConnection.name == name,
            )
        )

        if existing.scalar_one_or_none() is not None:
            raise ConflictException(
                f"A connection named '{name}' already exists."
            )

        connection = PlanningAnalyticsConnection(
            organization_id=organization_id,
            created_by=user_id,
            name=name,
            provider_type=provider.value,
            base_url=base_url,
            server_name=server_name,
            environment_type=environment_type,
            authentication_type=authentication_type,
            # Reuses the existing Fernet mechanism rather than adding a
            # second secret store.
            encrypted_credential=(
                encrypt_password(credential) if credential else None
            ),
            # Never enabled on creation: a connection becomes usable
            # only after a health check has actually succeeded.
            enabled=False,
            status=ConnectionHealth.UNKNOWN.value,
        )

        db.add(connection)

        await db.flush()
        await db.refresh(connection)

        return connection

    async def list_connections(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[PlanningAnalyticsConnection]:

        result = await db.execute(
            select(PlanningAnalyticsConnection)
            .where(
                PlanningAnalyticsConnection.organization_id == organization_id
            )
            .order_by(PlanningAnalyticsConnection.name)
        )

        return list(result.scalars().all())

    async def get(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> PlanningAnalyticsConnection:
        """Resolve within the caller's organization, or 404.

        The organization filter is in the WHERE clause, not applied
        after the fetch — a row belonging to another tenant is never
        loaded into memory in the first place.
        """

        result = await db.execute(
            select(PlanningAnalyticsConnection).where(
                PlanningAnalyticsConnection.id == connection_id,
                PlanningAnalyticsConnection.organization_id == organization_id,
            )
        )

        connection = result.scalar_one_or_none()

        if connection is None:
            # Same answer for "does not exist" and "belongs to someone
            # else". Distinguishing them would let a caller enumerate
            # other tenants' connection ids.
            raise NotFoundException("Connection not found.")

        return connection

    async def delete(
        self,
        db: AsyncSession,
        connection_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:

        connection = await self.get(db, connection_id, organization_id)

        await db.delete(connection)
        await db.flush()

    async def record_health(
        self,
        db: AsyncSession,
        connection: PlanningAnalyticsConnection,
        *,
        health: ConnectionHealth,
        provider_version: str | None = None,
        capabilities: list[str] | None = None,
        discovered_tools: list[dict] | None = None,
        error_category: str | None = None,
        error_message_safe: str | None = None,
    ) -> PlanningAnalyticsConnection:
        """Persist the outcome of a health check or discovery.

        `enabled` is derived from the result rather than set by a
        caller: a connection is usable exactly when its last check
        succeeded, so a failing connection cannot be left enabled by an
        administrator who did not re-check it.
        """

        connection.status = health.value
        connection.last_health_check = datetime.now(UTC)
        connection.enabled = health is ConnectionHealth.CONNECTED

        if provider_version is not None:
            connection.provider_version = provider_version[:100]

        if capabilities is not None:
            connection.capabilities = capabilities

        if discovered_tools is not None:
            connection.discovered_tools = discovered_tools

        connection.last_error_category = error_category

        # Truncated, and named `_safe` because only already-redacted
        # text may be stored: a transport error can embed the endpoint,
        # and an endpoint can embed a token.
        connection.last_error_message_safe = (
            error_message_safe[:_MAX_ERROR_CHARS] if error_message_safe else None
        )

        await db.flush()
        await db.refresh(connection)

        return connection


connection_service = ConnectionService()
