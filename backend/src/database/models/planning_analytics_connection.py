import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class PlanningAnalyticsConnection(BaseModel, OrganizationScoped):
    """A configured route to Planning Analytics, per organization.

    Phase 1.6 could implement the authorization gate but could not prove
    it, because there was nothing to own: with no persisted connection,
    "organization A cannot reach organization B's connection" was an
    assertion about code that never ran. This model is what makes that
    testable.

    Two fields carry most of the security weight:

    * `base_url` is administrator-supplied and is what the backend will
      connect to, so it is SSRF-validated before it is ever stored — see
      `planning_analytics/ssrf.py`. It is validated again at connect
      time, because DNS can move underneath a stored value.

    * `encrypted_credential` reuses the existing Fernet mechanism
      (`src/tm1/crypto.py`) rather than introducing a second secret
      store. Nothing here is ever serialized to an API response; the
      response schema names its fields explicitly so a column added
      later cannot leak by default.

    `last_error_message_safe` is named for the invariant it must hold:
    only messages that have already been through redaction go in it. An
    MCP transport error can embed the endpoint, and an endpoint can
    embed a token.
    """

    __tablename__ = "planning_analytics_connections"

    __table_args__ = (
        # Names are how humans refer to a connection, so they must be
        # unambiguous within a tenant — but only within it. Two
        # organizations may both have a "Production" connection.
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_pa_connections_org_name",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    #: ProviderType value. PAX is deliberately not a permitted value —
    #: it is a COM interface with no network form and belongs to the
    #: worker. Enforced in the service, not just by convention.
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)

    #: PA Local / PA on Cloud / Certified Containers / PAaaS. Recorded
    #: because IBM's MCP support and licensing differ by deployment
    #: model, so a support conversation starts from fact.
    environment_type: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )

    #: SSRF-validated before storage. Null for providers that have no
    #: URL (a PAfE worker is reached through the worker plane).
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    server_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: "oauth" | "none". Never a credential itself.
    authentication_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="none", server_default="none"
    )

    #: Fernet ciphertext via src/tm1/crypto.py. Never returned by any API.
    encrypted_credential: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    #: ConnectionHealth value from the last health check.
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )

    #: Capabilities proven by a live discovery against THIS connection.
    #: Empty until then — a capability is never inferred from the
    #: provider type, because that is how an untested integration comes
    #: to look supported.
    capabilities: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Normalized tool metadata from the last discovery, already risk
    #: classified. Cached so the inspector does not re-contact the
    #: server on every page view.
    discovered_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    provider_version: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_error_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    last_error_message_safe: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
