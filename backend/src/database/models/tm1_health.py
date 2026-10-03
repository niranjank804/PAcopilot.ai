import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel
from ..tenancy import OrganizationScoped


class TM1HealthScan(BaseModel, OrganizationScoped):
    """One model health scan: the score, and the evidence behind each point
    taken off it (src/tm1/health/score.py)."""

    __tablename__ = "tm1_health_scans"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # manual | schedule
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    # [{"category", "count", "points", "cap", "evidence": [...]}]
    deductions: Mapped[list] = mapped_column(JSONB, nullable=False)
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The worst findings, capped, for the page and the agents.
    findings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TM1ProcessRun(BaseModel, OrganizationScoped):
    """How long one process run took and how it ended. From TM1's message
    log, or recorded when PA-Copilot ran it — never estimated."""

    __tablename__ = "tm1_process_runs"
    __table_args__ = (
        UniqueConstraint("connection_id", "process_name", "finished_at", "source", name="uq_tm1_process_runs_run"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    process_name: Mapped[str] = mapped_column(String(255), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # succeeded | aborted | completed_with_errors | quit | other
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    # message_log | pa_copilot
    source: Mapped[str] = mapped_column(String(20), nullable=False)
