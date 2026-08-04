"""add_tm1_change_superseded_by

Revision ID: a1c7d94f2b60
Revises: 8f0b76be1e6f
Create Date: 2026-07-28 10:12:03.415502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7d94f2b60'
down_revision: Union[str, Sequence[str], None] = '8f0b76be1e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'tm1_changes',
        sa.Column('superseded_by', sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_tm1_changes_superseded_by',
        'tm1_changes',
        'tm1_changes',
        ['superseded_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_tm1_changes_superseded_by', 'tm1_changes', type_='foreignkey'
    )
    op.drop_column('tm1_changes', 'superseded_by')
