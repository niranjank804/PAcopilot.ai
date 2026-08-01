"""add_token_revocation

Two mechanisms, because they answer different questions.

`revoked_tokens` holds individually retired JWTs — a logout, or the old
refresh token superseded by a rotation. Keyed by jti and pruned once the
token's own expiry passes.

`users.tokens_valid_from` handles bulk revocation. Logging out everywhere,
changing a password or completing a reset must kill every outstanding
session, and the server never stored those tokens to enumerate them. A
single timestamp per user invalidates all tokens issued before it in one
write, checked against the token's `iat`.

Defaults to the epoch so every existing token stays valid — this migration
does not sign anyone out.

Revision ID: d5a80c3e91f7
Revises: d4a1e08c5b73
Create Date: 2026-08-01 09:14:22.518903

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5a80c3e91f7'
down_revision: Union[str, Sequence[str], None] = 'd4a1e08c5b73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'revoked_tokens',
        sa.Column('id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(length=32), nullable=False,
                  server_default='logout'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jti'),
    )
    op.create_index('ix_revoked_tokens_jti', 'revoked_tokens', ['jti'])
    op.create_index('ix_revoked_tokens_user_id', 'revoked_tokens', ['user_id'])
    # Supports the prune query, which deletes everything already expired.
    op.create_index(
        'ix_revoked_tokens_expires_at', 'revoked_tokens', ['expires_at']
    )

    op.add_column(
        'users',
        sa.Column(
            'tokens_valid_from',
            sa.DateTime(timezone=True),
            nullable=False,
            # Epoch: no existing session is invalidated by this migration.
            server_default=sa.text("'1970-01-01 00:00:00+00'"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'tokens_valid_from')
    op.drop_index('ix_revoked_tokens_expires_at', table_name='revoked_tokens')
    op.drop_index('ix_revoked_tokens_user_id', table_name='revoked_tokens')
    op.drop_index('ix_revoked_tokens_jti', table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
