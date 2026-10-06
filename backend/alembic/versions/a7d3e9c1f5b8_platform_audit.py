"""Platform audit: sign-in history, last activity, connection suspension.

Revision ID: a7d3e9c1f5b8
Revises: e8c4a2f6b9d3
Create Date: 2026-10-06

Additive only. A new table records each sign-in attempt; users gain when
they last signed in and were last active; connections gain a suspension the
platform owner sets, separate from the organization's own active flag.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7d3e9c1f5b8"
down_revision = "e8c4a2f6b9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)

    op.create_table(
        "sign_in_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organization_id", uuid, sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("identifier", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sign_in_events_user_id", "sign_in_events", ["user_id"])
    op.create_index("ix_sign_in_events_organization_id", "sign_in_events", ["organization_id"])
    op.create_index("ix_sign_in_events_created_at", "sign_in_events", ["created_at"])

    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("tm1_connections", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tm1_connections", sa.Column("suspended_reason", sa.String(length=500), nullable=True))
    op.add_column("tm1_connections", sa.Column(
        "suspended_by", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    ))

    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_column("tm1_connections", "suspended_by")
    op.drop_column("tm1_connections", "suspended_reason")
    op.drop_column("tm1_connections", "suspended_at")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "last_login_at")
    op.drop_table("sign_in_events")
