"""Continuous monitoring: rules and the alerts they raise.

Revision ID: d6b2f8e4a1c7
Revises: c3f8a1d5e9b2
Create Date: 2026-10-05

Two new tables. Nothing existing changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d6b2f8e4a1c7"
down_revision = "c3f8a1d5e9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()

    op.create_table(
        "monitor_rules",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("params", jsonb, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="human"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("notify", jsonb, nullable=False, server_default="[]"),
        sa.Column("state", jsonb, nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_monitor_rules_organization_id", "monitor_rules", ["organization_id"])
    op.create_index("ix_monitor_rules_connection_id", "monitor_rules", ["connection_id"])

    op.create_table(
        "monitor_alerts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", uuid, sa.ForeignKey("monitor_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence", jsonb, nullable=True),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("acknowledged_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rule_id", "dedup_key", name="uq_monitor_alerts_rule_key"),
    )
    op.create_index("ix_monitor_alerts_organization_id", "monitor_alerts", ["organization_id"])
    op.create_index("ix_monitor_alerts_connection_status", "monitor_alerts", ["connection_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_monitor_alerts_connection_status", table_name="monitor_alerts")
    op.drop_index("ix_monitor_alerts_organization_id", table_name="monitor_alerts")
    op.drop_table("monitor_alerts")
    op.drop_index("ix_monitor_rules_connection_id", table_name="monitor_rules")
    op.drop_index("ix_monitor_rules_organization_id", table_name="monitor_rules")
    op.drop_table("monitor_rules")
