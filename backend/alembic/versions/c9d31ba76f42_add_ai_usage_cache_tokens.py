"""add_ai_usage_cache_tokens

Records cached prompt tokens separately from prompt_tokens. Without these
two columns the effect of prompt caching is unmeasurable: the provider
reports cache reads and writes outside `input_tokens`, so a request served
almost entirely from cache looks like a request with a tiny prompt.

Backfills to 0, which is accurate — rows written before caching shipped
had no cache activity.

Revision ID: c9d31ba76f42
Revises: b4e2f81a37c9
Create Date: 2026-07-29 14:22:51.883104

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d31ba76f42'
down_revision: Union[str, Sequence[str], None] = 'b4e2f81a37c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'ai_usage',
        sa.Column(
            'cache_creation_tokens',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'ai_usage',
        sa.Column(
            'cache_read_tokens',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ai_usage', 'cache_read_tokens')
    op.drop_column('ai_usage', 'cache_creation_tokens')
