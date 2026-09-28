"""TM1 gateways: reach TM1 servers inside company networks.

Revision ID: e5a0c3b7d912
Revises: b8d3f2a61c47
Create Date: 2026-09-28

A TM1 server on a company network cannot be reached from the hosted
backend. A gateway installed inside that network connects out and carries
the requests (src/tm1/gateway). This adds the gateways, and on each TM1
connection an optional gateway it is reached through.

Additive only: a new table and a nullable column. Existing connections
keep gateway_id NULL and are reached directly, exactly as before.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a0c3b7d912"
down_revision = "b8d3f2a61c47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tm1_gateways",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_tm1_gateways_organization_id", "tm1_gateways", ["organization_id"]
    )

    op.add_column(
        "tm1_connections",
        sa.Column(
            "gateway_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tm1_gateways.id",
                name="fk_tm1_connections_gateway_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_tm1_connections_gateway_id", "tm1_connections", ["gateway_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tm1_connections_gateway_id", table_name="tm1_connections")
    op.drop_constraint(
        "fk_tm1_connections_gateway_id", "tm1_connections", type_="foreignkey"
    )
    op.drop_column("tm1_connections", "gateway_id")
    op.drop_index("ix_tm1_gateways_organization_id", table_name="tm1_gateways")
    op.drop_table("tm1_gateways")
