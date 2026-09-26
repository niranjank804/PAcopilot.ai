import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class AIConversation(BaseModel, OrganizationScoped):
    __tablename__ = "ai_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(255),
    )

    # Set when the product started the conversation for itself (e.g.
    # "visualize"), rather than a person in Chat. Such conversations are
    # kept — their usage rows are billing records — but left out of the
    # Chat history list.
    purpose: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
