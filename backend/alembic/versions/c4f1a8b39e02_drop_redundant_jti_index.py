"""drop the redundant non-unique index on revoked_tokens.jti

Revision ID: c4f1a8b39e02
Revises: b8e42c1d7a93
Create Date: 2026-08-13

The model declared `unique=True, index=True` on `jti`, which produced two
indexes on one column: the UNIQUE constraint's own index
(`revoked_tokens_jti_key`) and a separate non-unique `ix_revoked_tokens_jti`.

Postgres backs a UNIQUE constraint with a unique index, so the second one
answers no query the first cannot. It is pure cost: another index to
maintain on every token revocation, and more space, for nothing.

Dropping an index is non-destructive — no row is touched and the
uniqueness guarantee is unaffected, because it lives on the constraint.
The downgrade recreates it exactly.

This also removes the last piece of model/schema drift, so
`alembic check` is clean and autogenerate becomes trustworthy again.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c4f1a8b39e02"
down_revision: Union[str, Sequence[str], None] = "b8e42c1d7a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # if_exists: this index is absent on a database created after the
    # model was corrected, so a fresh environment must not fail here.
    op.execute("DROP INDEX IF EXISTS ix_revoked_tokens_jti")


def downgrade() -> None:
    """Downgrade schema."""

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_revoked_tokens_jti "
        "ON revoked_tokens (jti)"
    )
