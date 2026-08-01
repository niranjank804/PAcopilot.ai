"""one_open_draft_per_target

Adds a partial unique index so at most one draft change can be open per
(connection, target, author) at a time. Application-level supersession in
change_service already collapses the common case — several
propose_process_update calls in a single agent turn — but that check is a
read followed by a write, so two *separate* requests (a retried POST, two
browser tabs) can still interleave. Only the database can make it
impossible.

The index cannot be created while conflicting rows exist. Picking which
of several competing drafts survives is a judgement call about real
proposed TM1 changes, so this migration refuses to guess: it fails with
the offending groups listed and leaves resolution to an operator.

To resolve, for each group listed either reject the obsolete drafts
through the API, or mark them superseded directly:

    UPDATE tm1_changes SET status = 'superseded'
    WHERE id IN (<ids to retire>);

Revision ID: b4e2f81a37c9
Revises: a1c7d94f2b60
Create Date: 2026-07-29 09:41:18.220374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e2f81a37c9'
down_revision: Union[str, Sequence[str], None] = 'a1c7d94f2b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = 'uq_tm1_changes_open_draft'

_CONFLICTS = sa.text(
    """
    SELECT connection_id, created_by, target_name, COUNT(*) AS n
    FROM tm1_changes
    WHERE status = 'draft'
    GROUP BY connection_id, created_by, target_name
    HAVING COUNT(*) > 1
    ORDER BY n DESC
    """
)


def _assert_no_conflicts() -> None:
    rows = op.get_bind().execute(_CONFLICTS).fetchall()

    if not rows:
        return

    detail = "\n".join(
        f"  - target '{row.target_name}' on connection {row.connection_id} "
        f"(author {row.created_by}): {row.n} open drafts"
        for row in rows
    )

    raise RuntimeError(
        "Cannot add "
        f"{INDEX_NAME}: existing rows already violate it.\n"
        f"{detail}\n"
        "Each group needs a human decision about which draft survives — "
        "these are real proposed TM1 changes and their content differs. "
        "Retire the obsolete ones (status = 'superseded' or 'rejected'), "
        "then re-run this migration. See the module docstring for SQL."
    )


def upgrade() -> None:
    """Upgrade schema."""
    _assert_no_conflicts()

    op.create_index(
        INDEX_NAME,
        'tm1_changes',
        ['connection_id', 'created_by', 'target_name'],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(INDEX_NAME, table_name='tm1_changes')
