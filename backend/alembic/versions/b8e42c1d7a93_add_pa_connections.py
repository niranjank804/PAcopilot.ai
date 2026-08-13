"""add planning analytics connections

Revision ID: b8e42c1d7a93
Revises: a7d31f905c48
Create Date: 2026-08-13

Additive only — one new table, nothing existing touched, so there is no
existing data to migrate or lose. The downgrade is exact.

The unique constraint is scoped to (organization_id, name) rather than
name alone: two organizations may legitimately both call a connection
"Production", and a global unique name would leak the existence of
another tenant's connection through a constraint violation.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8e42c1d7a93"
down_revision: Union[str, Sequence[str], None] = "a7d31f905c48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "planning_analytics_connections",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=30), nullable=False),
        sa.Column("environment_type", sa.String(length=40), nullable=True),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("server_name", sa.String(length=200), nullable=True),
        sa.Column(
            "authentication_type",
            sa.String(length=30),
            server_default="none",
            nullable=False,
        ),
        sa.Column("encrypted_credential", sa.Text(), nullable=True),
        sa.Column(
            "enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=40), server_default="UNKNOWN", nullable=False
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "discovered_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("provider_version", sa.String(length=100), nullable=True),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=50), nullable=True),
        sa.Column("last_error_message_safe", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_pa_connections_org_name"
        ),
    )
    op.create_index(
        op.f("ix_planning_analytics_connections_organization_id"),
        "planning_analytics_connections",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_planning_analytics_connections_created_by"),
        "planning_analytics_connections",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        op.f("ix_planning_analytics_connections_created_by"),
        table_name="planning_analytics_connections",
    )
    op.drop_index(
        op.f("ix_planning_analytics_connections_organization_id"),
        table_name="planning_analytics_connections",
    )
    op.drop_table("planning_analytics_connections")
