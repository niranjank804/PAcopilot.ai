"""Work item documents; several open view drafts per cube.

Revision ID: d2f6b8a4c1e9
Revises: c9d4a7e2b6f3
Create Date: 2026-10-06

One new table. A pasted PBI with its acceptance criteria
needs more room than the old 10,000-character description, which is a
validation limit in the API, not a column change (the column is TEXT).

The open-draft index gains the view name, so one person can have several
"create view" drafts open on the same cube (a PBI's numbered evidence
views). For every other change type the added key is empty, so their rule
is unchanged.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d2f6b8a4c1e9"
down_revision = "c9d4a7e2b6f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)

    op.create_table(
        "work_item_documents",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", uuid, sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("drafted_by_assistant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("work_item_id", "title", name="uq_work_item_documents_title"),
    )
    op.create_index("ix_work_item_documents_work_item_id", "work_item_documents", ["work_item_id"])

    op.drop_index("uq_tm1_changes_open_draft", table_name="tm1_changes")
    op.execute(
        "CREATE UNIQUE INDEX uq_tm1_changes_open_draft ON tm1_changes "
        "(connection_id, created_by, target_name, (coalesce(new_content ->> 'view_name', ''))) "
        "WHERE status = 'draft'"
    )


def downgrade() -> None:
    op.drop_index("uq_tm1_changes_open_draft", table_name="tm1_changes")
    op.create_index(
        "uq_tm1_changes_open_draft", "tm1_changes", ["connection_id", "created_by", "target_name"],
        unique=True, postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_table("work_item_documents")
