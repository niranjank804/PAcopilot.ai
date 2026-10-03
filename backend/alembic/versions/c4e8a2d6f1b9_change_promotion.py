"""A change promoted from a lower environment knows where it came from.

Revision ID: c4e8a2d6f1b9
Revises: b7d1f0c3e9a5
Create Date: 2026-10-03

tm1_changes.promoted_from points a QA or PROD draft at the change it was
promoted from (DEV -> QA -> PROD). Following it gives the chain: which
environments the change passed through, who approved it in each, and what
was verified there — the evidence a production approver needs.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4e8a2d6f1b9"
down_revision = "b7d1f0c3e9a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tm1_changes",
        sa.Column(
            "promoted_from",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tm1_changes.id", ondelete="SET NULL", name="fk_tm1_changes_promoted_from"),
            nullable=True,
        ),
    )
    op.create_index("ix_tm1_changes_promoted_from", "tm1_changes", ["promoted_from"])


def downgrade() -> None:
    op.drop_index("ix_tm1_changes_promoted_from", table_name="tm1_changes")
    op.drop_constraint("fk_tm1_changes_promoted_from", "tm1_changes", type_="foreignkey")
    op.drop_column("tm1_changes", "promoted_from")
