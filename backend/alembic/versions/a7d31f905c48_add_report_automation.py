"""add report automation (workers, workbooks, definitions, executions, artifacts)

Revision ID: a7d31f905c48
Revises: 068abcff8dda
Create Date: 2026-08-12

Additive only — creates six new tables and touches nothing that exists,
so there is no existing data to inspect, migrate, or lose. The downgrade
drops them in dependency order and is exact.

Two constraints in here are load-bearing rather than hygienic:

* uq_report_executions_org_idempotency_key is what makes a duplicated
  scheduler tick produce one execution instead of two. It must exist in
  the database, not only in application code — two API processes racing
  cannot see each other's uncommitted inserts.
* uq_report_artifacts_execution_format is what makes a retried artifact
  upload idempotent.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7d31f905c48"
down_revision: Union[str, Sequence[str], None] = "068abcff8dda"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "report_blobs",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_blobs_organization_id"),
        "report_blobs",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "report_workers",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("enrollment_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "enrollment_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secret_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "secret_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("secret_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(length=30), nullable=True),
        sa.Column("os", sa.String(length=100), nullable=True),
        sa.Column("excel_version", sa.String(length=50), nullable=True),
        sa.Column("pafe_version", sa.String(length=50), nullable=True),
        sa.Column("hostname", sa.String(length=100), nullable=True),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_workers_organization_id"),
        "report_workers",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_workers_created_by"),
        "report_workers",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_workers_last_heartbeat_at"),
        "report_workers",
        ["last_heartbeat_at"],
        unique=False,
    )
    # An enrollment token is presented *before* the caller has any
    # identity, so the lookup is by token hash alone. Unique because two
    # workers sharing an enrollment secret would be a cross-worker
    # impersonation path, and partial because the column is NULL for every
    # worker that already enrolled.
    op.create_index(
        "uq_report_workers_enrollment_token_hash",
        "report_workers",
        ["enrollment_token_hash"],
        unique=True,
        postgresql_where=sa.text("enrollment_token_hash IS NOT NULL"),
    )

    op.create_table(
        "report_workbooks",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("filename", sa.String(length=128), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("storage_reference", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "compatibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_workbooks_organization_id"),
        "report_workbooks",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_workbooks_created_by"),
        "report_workbooks",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_workbooks_checksum"),
        "report_workbooks",
        ["checksum"],
        unique=False,
    )

    op.create_table(
        "report_definitions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("report_type", sa.String(length=30), nullable=False),
        sa.Column("workbook_id", sa.UUID(), nullable=True),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("worker_id", sa.UUID(), nullable=True),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "output_formats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "delivery_configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "approval_status",
            sa.String(length=20),
            server_default="not_required",
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workbook_id"], ["report_workbooks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["tm1_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["report_workers.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_definitions_organization_id"),
        "report_definitions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_definitions_created_by"),
        "report_definitions",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_definitions_workbook_id"),
        "report_definitions",
        ["workbook_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_definitions_connection_id"),
        "report_definitions",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_definitions_worker_id"),
        "report_definitions",
        ["worker_id"],
        unique=False,
    )

    op.create_table(
        "report_executions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("workbook_id", sa.UUID(), nullable=True),
        sa.Column("worker_id", sa.UUID(), nullable=True),
        sa.Column("triggered_by", sa.UUID(), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "max_attempts", sa.Integer(), server_default="3", nullable=False
        ),
        sa.Column("parent_execution_id", sa.UUID(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_class", sa.String(length=20), nullable=True),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("trace_log", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["report_id"], ["report_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workbook_id"], ["report_workbooks.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["report_workers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_execution_id"], ["report_executions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_report_executions_org_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_report_executions_organization_id"),
        "report_executions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_report_id"),
        "report_executions",
        ["report_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_worker_id"),
        "report_executions",
        ["worker_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_status"),
        "report_executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_correlation_id"),
        "report_executions",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_available_at"),
        "report_executions",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_lease_expires_at"),
        "report_executions",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_executions_parent_execution_id"),
        "report_executions",
        ["parent_execution_id"],
        unique=False,
    )
    # The claim query's exact access path: eligible rows for one org,
    # oldest first. Without it every claim sequentially scans a table that
    # only ever grows.
    op.create_index(
        "ix_report_executions_claimable",
        "report_executions",
        ["organization_id", "status", "available_at"],
        unique=False,
    )

    op.create_table(
        "report_artifacts",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("report_execution_id", sa.UUID(), nullable=False),
        sa.Column("output_format", sa.String(length=10), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_reference", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["report_execution_id"],
            ["report_executions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_execution_id",
            "output_format",
            name="uq_report_artifacts_execution_format",
        ),
    )
    op.create_index(
        op.f("ix_report_artifacts_organization_id"),
        "report_artifacts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_artifacts_report_execution_id"),
        "report_artifacts",
        ["report_execution_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        op.f("ix_report_artifacts_report_execution_id"),
        table_name="report_artifacts",
    )
    op.drop_index(
        op.f("ix_report_artifacts_organization_id"), table_name="report_artifacts"
    )
    op.drop_table("report_artifacts")

    op.drop_index(
        "ix_report_executions_claimable", table_name="report_executions"
    )
    op.drop_index(
        op.f("ix_report_executions_parent_execution_id"),
        table_name="report_executions",
    )
    op.drop_index(
        op.f("ix_report_executions_lease_expires_at"),
        table_name="report_executions",
    )
    op.drop_index(
        op.f("ix_report_executions_available_at"), table_name="report_executions"
    )
    op.drop_index(
        op.f("ix_report_executions_correlation_id"),
        table_name="report_executions",
    )
    op.drop_index(
        op.f("ix_report_executions_status"), table_name="report_executions"
    )
    op.drop_index(
        op.f("ix_report_executions_worker_id"), table_name="report_executions"
    )
    op.drop_index(
        op.f("ix_report_executions_report_id"), table_name="report_executions"
    )
    op.drop_index(
        op.f("ix_report_executions_organization_id"),
        table_name="report_executions",
    )
    op.drop_table("report_executions")

    op.drop_index(
        op.f("ix_report_definitions_worker_id"), table_name="report_definitions"
    )
    op.drop_index(
        op.f("ix_report_definitions_connection_id"),
        table_name="report_definitions",
    )
    op.drop_index(
        op.f("ix_report_definitions_workbook_id"), table_name="report_definitions"
    )
    op.drop_index(
        op.f("ix_report_definitions_created_by"), table_name="report_definitions"
    )
    op.drop_index(
        op.f("ix_report_definitions_organization_id"),
        table_name="report_definitions",
    )
    op.drop_table("report_definitions")

    op.drop_index(
        op.f("ix_report_workbooks_checksum"), table_name="report_workbooks"
    )
    op.drop_index(
        op.f("ix_report_workbooks_created_by"), table_name="report_workbooks"
    )
    op.drop_index(
        op.f("ix_report_workbooks_organization_id"), table_name="report_workbooks"
    )
    op.drop_table("report_workbooks")

    op.drop_index(
        "uq_report_workers_enrollment_token_hash", table_name="report_workers"
    )
    op.drop_index(
        op.f("ix_report_workers_last_heartbeat_at"), table_name="report_workers"
    )
    op.drop_index(
        op.f("ix_report_workers_created_by"), table_name="report_workers"
    )
    op.drop_index(
        op.f("ix_report_workers_organization_id"), table_name="report_workers"
    )
    op.drop_table("report_workers")

    op.drop_index(op.f("ix_report_blobs_organization_id"), table_name="report_blobs")
    op.drop_table("report_blobs")
