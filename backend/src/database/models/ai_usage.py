import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class AIUsage(BaseModel, OrganizationScoped):
    __tablename__ = "ai_usage"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_conversations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_messages.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

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

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Cached prompt tokens, recorded apart from prompt_tokens because they
    # are priced differently and because the hit rate is only measurable
    # if reads and writes are kept distinct. Not a subset of prompt_tokens:
    # that field is the uncached remainder.
    cache_creation_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    cache_read_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6),
        nullable=False,
    )

    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Which specialist agent ran the turn (None for plain chat), the routing
    # tier it ran on and why (src/ai/routing.py), and whether it fell back to
    # the neighbouring tier — for cost per agent and the fallback rate.
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    route_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fell_back: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
