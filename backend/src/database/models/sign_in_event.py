import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class SignInEvent(BaseModel):
    """One attempt to sign in, successful or not, for the platform owner.

    Deliberately not OrganizationScoped: a failed attempt may name no
    account at all, so there is no organization to scope it to, and only
    the Super Admin's platform view reads these rows (src/api/v1/platform.py).
    """

    __tablename__ = "sign_in_events"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # What was typed (username or email), cut short. Kept for failures that
    # match no account, which is what a password-guessing run looks like.
    identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False)  # password | google
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
