import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class AIUsage(BaseModel):
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

    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6),
        nullable=False,
    )

    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
