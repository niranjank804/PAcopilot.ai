"""Temporary passwords handed out by the Super Admin.

Revision ID: f7b2d9e4a1c6
Revises: e5a1c7d3f9b2
Create Date: 2026-10-31

Additive. A Super Admin can give a locked-out person a one-time password
(Platform → Users) when no reset email can reach them. While it is in
force the account may do one thing — set a password of its own — and the
one-time password stops signing in at the expiry. Existing rows get
must_change_password = false, so nobody is interrupted.
"""

import sqlalchemy as sa
from alembic import op

revision = "f7b2d9e4a1c6"
down_revision = "e5a1c7d3f9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "must_change_password", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("users", sa.Column(
        "temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("users", "temporary_password_expires_at")
    op.drop_column("users", "must_change_password")
