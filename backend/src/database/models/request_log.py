import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class RequestLog(BaseModel):
    """Every API request a person made: who, what, when, from where, and
    how it ended. Written by src/middleware/request_log.py.

    The audit log records what an action meant (a change executed, a user
    deactivated); this records that a request happened at all, so nothing
    a person does through the API goes unrecorded. Request bodies are never
    stored — they can hold passwords and TM1 credentials.

    Not OrganizationScoped: only the platform owner reads it, and the
    organization is the user's, joined at read time.
    """

    __tablename__ = "request_logs"
    __table_args__ = (
        Index("ix_request_logs_created_at", "created_at"),
        Index("ix_request_logs_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # The route as declared, e.g. /tm1/connections/{connection_id}/cubes,
    # so requests can be grouped by what they do rather than by their ids.
    route: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
