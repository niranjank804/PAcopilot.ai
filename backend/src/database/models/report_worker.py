import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class ReportWorker(BaseModel, OrganizationScoped):
    """A customer-operated Windows machine that runs Excel and PAfE.

    Credential design, and why it is not an API key column:

    * `enrollment_token_hash` is a single-use, short-lived secret an
      administrator copies out of the console once. It can only be spent
      to complete enrollment — it cannot claim jobs or read data.
    * `secret_hash` is the long-lived machine credential, issued at
      enrollment and never returned again. It is only accepted at the
      token endpoint; every other worker call presents a short-lived JWT.
    * `secret_version` is bumped on rotation. It is embedded in issued
      tokens, so rotating invalidates every token already in flight
      without needing a revocation list.

    Both secrets are stored as HMAC-SHA256 digests keyed with the app's
    SECRET_KEY rather than as plaintext or as bare hashes: these are
    high-entropy machine secrets (not human passwords, so argon2's work
    factor buys nothing), and keying the digest means a leaked database
    dump alone is not enough to forge one.
    """

    __tablename__ = "report_workers"

    __table_args__ = (
        # An enrollment token is presented before the caller has any
        # identity, so it is looked up by hash alone — which makes
        # uniqueness a security property, not just hygiene. Partial,
        # because the column is NULL for every worker already enrolled
        # and NULLs must not collide with each other.
        Index(
            "uq_report_workers_enrollment_token_hash",
            "enrollment_token_hash",
            unique=True,
            postgresql_where=text("enrollment_token_hash IS NOT NULL"),
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

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_enrollment",
    )

    # --- Enrollment (single-use) ---

    enrollment_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    enrollment_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- Long-lived machine credential ---

    secret_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    secret_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    secret_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- Verified host facts, reported at enrollment and each heartbeat ---

    version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    os: Mapped[str | None] = mapped_column(String(100), nullable=True)
    excel_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pafe_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # List of WorkerCapability values the worker's own probe confirmed.
    capabilities: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Last self-reported error from the worker (redacted, safe to display).
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
