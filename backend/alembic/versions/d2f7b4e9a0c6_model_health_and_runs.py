"""Model health scans and the process run history.

Revision ID: d2f7b4e9a0c6
Revises: c4e8a2d6f1b9
Create Date: 2026-10-03

tm1_health_scans keeps every health scan of a connection with its score and
the evidence behind each deduction, so health can be followed over time.

tm1_process_runs keeps how long each process run took and how it ended —
read from TM1's message log, or recorded when PA-Copilot ran it — so a run
that suddenly takes ten times as long can be told from one that always did.
Two new tables; nothing existing changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "d2f7b4e9a0c6"
down_revision = "c4e8a2d6f1b9"
branch_labels = None
depends_on = None


def _owned_by_connection():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    ]


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tm1_health_scans",
        *_owned_by_connection(),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=2), nullable=False),
        sa.Column("deductions", postgresql.JSONB(), nullable=False),
        sa.Column("totals", postgresql.JSONB(), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "tm1_process_runs",
        *_owned_by_connection(),
        sa.Column("process_name", sa.String(length=255), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "connection_id", "process_name", "finished_at", "source",
            name="uq_tm1_process_runs_run",
        ),
    )
    op.create_index(
        "ix_tm1_process_runs_lookup", "tm1_process_runs", ["connection_id", "process_name", "finished_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tm1_process_runs_lookup", table_name="tm1_process_runs")
    op.drop_table("tm1_process_runs")
    op.drop_table("tm1_health_scans")
