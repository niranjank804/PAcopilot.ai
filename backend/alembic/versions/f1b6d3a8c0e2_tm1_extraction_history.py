"""History of metadata extractions, and what each found changed.

Revision ID: f1b6d3a8c0e2
Revises: c7e2a9f14b3d
Create Date: 2026-10-03

The dependency graph is rebuilt on every extraction, so on its own it can
only describe the model as it is now. tm1_extractions keeps one row per
extraction with the objects and dependencies that appeared or disappeared
since the previous one. A new table only: nothing existing changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1b6d3a8c0e2"
down_revision = "c7e2a9f14b3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tm1_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relationship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_references", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tm1_extractions_connection_id", "tm1_extractions", ["connection_id"])
    op.create_index("ix_tm1_extractions_organization_id", "tm1_extractions", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_tm1_extractions_organization_id", table_name="tm1_extractions")
    op.drop_index("ix_tm1_extractions_connection_id", table_name="tm1_extractions")
    op.drop_table("tm1_extractions")
