import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class MonitorRule(BaseModel, OrganizationScoped):
    """Something to watch on one TM1 server: "alert me if Load Workforce
    takes more than twice its 30-day average".

    A rule only reads. It never changes TM1 and never starts anything; what
    it finds becomes an alert for people to act on. A rule the assistant
    suggests starts `proposed` and is not checked until a person turns it
    on.
    """

    __tablename__ = "monitor_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # process_failure | performance_regression | dimension_growth |
    # security_change | model_change | deployment
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # active | paused | proposed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # human | ai
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="human")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # User ids to email when it fires.
    notify: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # What the last check saw: a baseline to compare the next one with.
    state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class MonitorAlert(BaseModel, OrganizationScoped):
    """One thing a rule found. Raised once per occurrence (`dedup_key`),
    then acknowledged and resolved by people."""

    __tablename__ = "monitor_alerts"
    __table_args__ = (UniqueConstraint("rule_id", "dedup_key", name="uq_monitor_alerts_rule_key"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitor_rules.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False
    )
    # info | warning | critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # open | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emailed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
