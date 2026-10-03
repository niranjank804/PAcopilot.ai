"""Pre-deployment checks and the server state a draft was made against.

Revision ID: a3c9e5f71b24
Revises: f1b6d3a8c0e2
Create Date: 2026-10-03

tm1_changes.base_fingerprint is a hash of the target as it was on the
server when the draft was made (the rules text, or the process's code). At
approval it is compared with the server again: if someone edited the object
in TM1 in between, the draft would overwrite their work, so it is refused.

tm1_changes.checks is the pre-deployment checklist shown to the approver:
static analysis, server compile, code review, impact, parameters. Both
nullable — drafts made before this migration have neither and behave as
before.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3c9e5f71b24"
down_revision = "f1b6d3a8c0e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tm1_changes", sa.Column("base_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("tm1_changes", sa.Column("checks", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tm1_changes", "checks")
    op.drop_column("tm1_changes", "base_fingerprint")
