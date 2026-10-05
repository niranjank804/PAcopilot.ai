"""Incident mode: incidents are work items, investigations are kept.

Revision ID: e8c4a2f6b9d3
Revises: d6b2f8e4a1c7
Create Date: 2026-10-05

Additive only. Existing work items become kind 'work'; one new table keeps
each investigation's findings.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e8c4a2f6b9d3"
down_revision = "d6b2f8e4a1c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)

    op.add_column("work_items", sa.Column("kind", sa.String(length=20), nullable=False, server_default="work"))
    op.add_column("work_items", sa.Column("severity", sa.String(length=20), nullable=True))
    op.add_column("work_items", sa.Column(
        "connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="SET NULL"), nullable=True,
    ))
    op.add_column("work_items", sa.Column("cube_name", sa.String(length=255), nullable=True))
    op.add_column("work_items", sa.Column("process_name", sa.String(length=255), nullable=True))

    op.create_table(
        "incident_investigations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", uuid, sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_incident_investigations_work_item_id", "incident_investigations", ["work_item_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_investigations_work_item_id", table_name="incident_investigations")
    op.drop_table("incident_investigations")
    for column in ("process_name", "cube_name", "connection_id", "severity", "kind"):
        op.drop_column("work_items", column)
