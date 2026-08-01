"""Add tm1_coding_conventions

Revision ID: f7c2b91d4e60
Revises: d5a80c3e91f7
Create Date: 2026-08-02

Stores the coding conventions measured from an organization's own exported
TurboIntegrator processes, so generated code can be grounded in how that team
actually writes TM1 rather than in generic style.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f7c2b91d4e60"
down_revision = "d5a80c3e91f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tm1_coding_conventions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("convention_key", sa.String(length=100), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("support", sa.Integer(), nullable=False),
        sa.Column("sample", sa.Integer(), nullable=False),
        sa.Column(
            "examples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "counter_examples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "convention_key",
            name="uq_tm1_coding_conventions_org_key",
        ),
    )
    op.create_index(
        op.f("ix_tm1_coding_conventions_organization_id"),
        "tm1_coding_conventions",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tm1_coding_conventions_organization_id"),
        table_name="tm1_coding_conventions",
    )
    op.drop_table("tm1_coding_conventions")
