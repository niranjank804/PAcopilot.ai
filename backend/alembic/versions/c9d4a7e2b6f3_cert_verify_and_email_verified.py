"""Per-connection certificate checking; confirmed email addresses.

Revision ID: c9d4a7e2b6f3
Revises: b3e8f2a6c4d1
Create Date: 2026-10-06

Additive. Existing connections keep today's behaviour (certificate not
checked) until their owner turns checking on; new ones check by default.
Existing accounts count as confirmed, so nobody is locked out of Google
sign-in; new password sign-ups are confirmed by a password reset (which
proves the mailbox) or are Google sign-ups to begin with.
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d4a7e2b6f3"
down_revision = "b3e8f2a6c4d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tm1_connections", sa.Column(
        "verify_ssl", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified_at = now()")


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
    op.drop_column("tm1_connections", "verify_ssl")
