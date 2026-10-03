"""Which agent and routing tier each AI request used, and whether it fell back.

Revision ID: e6a1c8d3f5b7
Revises: f9b3d5e7a1c2
Create Date: 2026-10-03

ai_usage gains agent, tier, route_reason and fell_back, so cost can be
reported per agent and per tier, and the fallback rate measured. All
nullable or defaulted: earlier rows have none of them and report as
"unknown".
"""

import sqlalchemy as sa
from alembic import op

revision = "e6a1c8d3f5b7"
down_revision = "f9b3d5e7a1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage", sa.Column("agent", sa.String(length=50), nullable=True))
    op.add_column("ai_usage", sa.Column("tier", sa.String(length=20), nullable=True))
    op.add_column("ai_usage", sa.Column("route_reason", sa.String(length=200), nullable=True))
    op.add_column(
        "ai_usage",
        sa.Column("fell_back", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("ai_usage", "fell_back")
    op.drop_column("ai_usage", "route_reason")
    op.drop_column("ai_usage", "tier")
    op.drop_column("ai_usage", "agent")
