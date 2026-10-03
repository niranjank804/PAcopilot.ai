"""Each TM1 connection is DEV, QA or PROD.

Revision ID: b7d1f0c3e9a5
Revises: a3c9e5f71b24
Create Date: 2026-10-03

tm1_connections.environment decides who may apply changes there (see
src/tm1/governance.py). Existing connections become DEV, so nothing that
works today changes until a connection is relabelled.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d1f0c3e9a5"
down_revision = "a3c9e5f71b24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tm1_connections",
        sa.Column("environment", sa.String(length=10), nullable=False, server_default="dev"),
    )
    op.create_check_constraint(
        "ck_tm1_connections_environment",
        "tm1_connections",
        "environment IN ('dev', 'qa', 'prod')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tm1_connections_environment", "tm1_connections", type_="check")
    op.drop_column("tm1_connections", "environment")
