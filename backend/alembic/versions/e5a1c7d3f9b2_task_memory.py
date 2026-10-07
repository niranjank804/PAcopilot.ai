"""Task memory: ai_tasks and their append-only events.

Revision ID: e5a1c7d3f9b2
Revises: d2f6b8a4c1e9
Create Date: 2026-10-07

Additive only: two new tables. Conversations, messages, engineering
memory and work items are unchanged and referenced by foreign key.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a1c7d3f9b2"
down_revision = "d2f6b8a4c1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()

    op.create_table(
        "ai_tasks",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", uuid, sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", uuid, sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connection_id", uuid, sa.ForeignKey("tm1_connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("state", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_turn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_tasks_organization_id", "ai_tasks", ["organization_id"])
    op.create_index("ix_ai_tasks_conversation_id", "ai_tasks", ["conversation_id"])
    op.create_index("ix_ai_tasks_work_item_id", "ai_tasks", ["work_item_id"])
    op.create_index("ix_ai_tasks_connection_id", "ai_tasks", ["connection_id"])
    op.create_index("ix_ai_tasks_user_updated", "ai_tasks", ["user_id", "updated_at"])

    op.create_table(
        "ai_task_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", uuid, sa.ForeignKey("ai_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("data", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_task_events_task_id", "ai_task_events", ["task_id"])


def downgrade() -> None:
    op.drop_table("ai_task_events")
    op.drop_table("ai_tasks")
