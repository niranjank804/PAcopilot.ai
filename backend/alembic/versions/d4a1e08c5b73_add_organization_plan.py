"""add_organization_plan

Records which plan an organization is on. The plan catalog itself lives in
code (src/billing/plans.py) — only the assignment is stored, so entitlements
version with the deploy rather than drifting in the database.

Backfills every existing row to 'trial', which is accurate: before this
column existed there were no paid organizations, and the trial limit is the
most generous one that is still metered. An operator can move a row to
'internal' to unmeter it.

NOT NULL with a server default, so the column is safe to add against a live
table and older application instances that do not set it still insert valid
rows during a rolling deploy.

Revision ID: d4a1e08c5b73
Revises: c9d31ba76f42
Create Date: 2026-07-30 09:14:22.104517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a1e08c5b73"
down_revision: Union[str, None] = "c9d31ba76f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "plan",
            sa.String(length=50),
            nullable=False,
            server_default="trial",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "plan")
