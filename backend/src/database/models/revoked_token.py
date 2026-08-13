import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class RevokedToken(BaseModel):
    """A single JWT that must no longer be accepted.

    Only *individual* revocations live here — a logout, or the old refresh
    token retired by a rotation. Bulk revocation (logout-everywhere,
    password change, password reset) is handled by users.tokens_valid_from
    instead, because writing one row per outstanding token would mean
    enumerating tokens the server never stored.

    Deliberately not OrganizationScoped: revocation is checked during
    authentication, before an organization is known. Rows are keyed by jti,
    which is a random UUID, so there is nothing to scope.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        # `unique=True` alone. Postgres backs a UNIQUE constraint with a
        # unique index, so adding `index=True` here created a *second*,
        # non-unique index on the same column — paid for on every insert
        # and every revocation sweep, for nothing. Migration
        # c4f1a8b39e02 drops the redundant one.
        unique=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The token's own expiry. Once past, the JWT fails signature/exp checks
    # on its own and the row is dead weight — this is what lets the table be
    # pruned instead of growing forever.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    reason: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="logout",
        server_default=text("'logout'"),
    )
