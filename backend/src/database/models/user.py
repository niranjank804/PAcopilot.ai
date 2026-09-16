from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class User(BaseModel, OrganizationScoped):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # "pending" | "approved" | "rejected" — separate from is_active, which
    # is for an admin disabling an already-approved account. Existing rows
    # (created before self-registration existed) default to "approved" via
    # server_default so this migration doesn't lock anyone out.
    # Every token issued before this instant is rejected, whatever
    # its own expiry says. One write logs the user out everywhere —
    # used by logout-all, password change and password reset, none
    # of which can enumerate outstanding tokens the server never
    # stored. Epoch default means 'nothing revoked'.
    tokens_valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("'1970-01-01 00:00:00+00'"),
    )

    # When the product tour was finished or dismissed. Nullable means
    # "never seen it", which is what a first login looks like.
    #
    # Server-side rather than localStorage because it is a property of
    # the person, not the browser: signing in on a second machine should
    # not replay an introduction they have already sat through, and
    # clearing site data should not either.
    #
    # Two columns rather than one status string. "Finished" and
    # "dismissed" differ in what they permit next — a dismissal is a
    # "not now" that may be offered again, a completion is not — and a
    # single enum would have to be re-parsed at every call site to
    # recover that distinction.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    onboarding_dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    registration_status: Mapped[str] = mapped_column(
        String(20),
        default="approved",
        server_default="approved",
        nullable=False,
    )

    organization = relationship(
        "Organization",
        back_populates="users",
    )
    user_roles = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )