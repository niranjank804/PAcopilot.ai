"""Engineering memory: what the team knows that the TM1 model cannot say.

Revision ID: a8c2e6f0b4d1
Revises: e6a1c8d3f5b7
Create Date: 2026-10-03

One new table, engineering_memories, organization-scoped and versioned.
Nothing existing changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a8c2e6f0b4d1"
down_revision = "e6a1c8d3f5b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "engineering_memories",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("object_type", sa.String(length=20), nullable=True),
        sa.Column("object_name", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes", uuid, sa.ForeignKey("engineering_memories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decided_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'archived')", name="ck_engineering_memories_status"
        ),
        sa.CheckConstraint(
            "kind IN ('convention', 'sequence', 'caution', 'known_issue', 'note')", name="ck_engineering_memories_kind"
        ),
    )
    op.create_index("ix_engineering_memories_organization_id", "engineering_memories", ["organization_id"])
    op.create_index("ix_engineering_memories_connection_id", "engineering_memories", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_engineering_memories_connection_id", table_name="engineering_memories")
    op.drop_index("ix_engineering_memories_organization_id", table_name="engineering_memories")
    op.drop_table("engineering_memories")
