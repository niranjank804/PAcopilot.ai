"""Team collaboration: shared conversations and work items.

Revision ID: c3f8a1d5e9b2
Revises: a8c2e6f0b4d1
Create Date: 2026-10-05

Additive only. Every existing conversation stays private (the column
defaults to 'private'); two new tables hold work items and what is linked
to them.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3f8a1d5e9b2"
down_revision = "a8c2e6f0b4d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)

    op.add_column(
        "ai_conversations",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
    )

    op.create_table(
        "work_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "reference", name="uq_work_items_org_reference"),
    )
    op.create_index("ix_work_items_organization_id", "work_items", ["organization_id"])

    op.create_table(
        "work_item_links",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", uuid, sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("target_id", uuid, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("linked_by", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("work_item_id", "kind", "target_id", name="uq_work_item_links_target"),
    )
    op.create_index("ix_work_item_links_work_item_id", "work_item_links", ["work_item_id"])
    op.create_index("ix_work_item_links_target_id", "work_item_links", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_work_item_links_target_id", table_name="work_item_links")
    op.drop_index("ix_work_item_links_work_item_id", table_name="work_item_links")
    op.drop_table("work_item_links")
    op.drop_index("ix_work_items_organization_id", table_name="work_items")
    op.drop_table("work_items")
    op.drop_column("ai_conversations", "visibility")
