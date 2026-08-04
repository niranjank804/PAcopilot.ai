"""add tm1_processes and tm1_process_patterns

Revision ID: 068abcff8dda
Revises: f7c2b91d4e60
Create Date: 2026-08-04

Persists what the deterministic TI pipeline already computes and previously
discarded: the parsed structure of each process, and the patterns it was found
to implement.

Hand-trimmed. `alembic revision --autogenerate` additionally proposed dropping
the unique constraint on `revoked_tokens.jti` and the `uq_tm1_changes_open_draft`
partial index, and removing server defaults on `tm1_coding_conventions`. Those
come from pre-existing drift between the models and the hand-written migrations,
not from this change — and both dropped constraints are load-bearing (token
replay, one open draft per target). They are deliberately not included here.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "068abcff8dda"
down_revision = "f7c2b91d4e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tm1_processes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "datasource_type", sa.String(length=50), nullable=False, server_default="none"
        ),
        sa.Column("header_comment", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "has_stored_credentials",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "line_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "objects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "functions_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "process_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("object_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("organization_id", "name", name="uq_tm1_processes_org_name"),
    )
    op.create_index(
        op.f("ix_tm1_processes_organization_id"),
        "tm1_processes",
        ["organization_id"],
    )

    op.create_table(
        "tm1_process_patterns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("process_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pattern_key", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "evidence",
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
        sa.ForeignKeyConstraint(
            ["process_id"], ["tm1_processes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "process_id", "pattern_key", name="uq_tm1_process_patterns_process_key"
        ),
    )
    op.create_index(
        op.f("ix_tm1_process_patterns_organization_id"),
        "tm1_process_patterns",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_tm1_process_patterns_process_id"),
        "tm1_process_patterns",
        ["process_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tm1_process_patterns_process_id"), table_name="tm1_process_patterns"
    )
    op.drop_index(
        op.f("ix_tm1_process_patterns_organization_id"),
        table_name="tm1_process_patterns",
    )
    op.drop_table("tm1_process_patterns")
    op.drop_index(
        op.f("ix_tm1_processes_organization_id"), table_name="tm1_processes"
    )
    op.drop_table("tm1_processes")
