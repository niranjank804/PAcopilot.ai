"""track whether a user has seen the product tour

Revision ID: a3d7e91c40b2
Revises: f1c9a4e77b28
Create Date: 2026-09-16

Server-side rather than in the browser: whether someone has been
introduced to the product is a fact about the person, not about a
device. localStorage would replay the tour on a second machine and
forget it when site data is cleared.

Both columns are nullable, and null means "never seen it" — which is
exactly the state every existing row should be in. Backfilling them to
`now()` would be the tempting shortcut and the wrong one: it would mark
every current user as having completed a tour that did not exist when
they signed up, so nobody who is already here would ever be offered it.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3d7e91c40b2"
down_revision = "f1c9a4e77b28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "onboarding_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "onboarding_dismissed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_dismissed_at")
    op.drop_column("users", "onboarding_completed_at")
