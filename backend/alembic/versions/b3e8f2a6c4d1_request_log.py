"""Request log: every API request a person makes; changes keep their environment.

Revision ID: b3e8f2a6c4d1
Revises: a7d3e9c1f5b8
Create Date: 2026-10-06

Additive only: one new table, whose rows older than the retention period
are purged by the daily cron, and a nullable column recording the
environment a change was drafted on, so relabelling a connection later
cannot loosen the rules for it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3e8f2a6c4d1"
down_revision = "a7d3e9c1f5b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)

    op.create_table(
        "request_logs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("route", sa.String(length=300), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("connection_id", uuid, nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_logs_created_at", "request_logs", ["created_at"])
    op.create_index("ix_request_logs_user_created", "request_logs", ["user_id", "created_at"])

    op.add_column("tm1_changes", sa.Column("environment", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("tm1_changes", "environment")
    op.drop_table("request_logs")
