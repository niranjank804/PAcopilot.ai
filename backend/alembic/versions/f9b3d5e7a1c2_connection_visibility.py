"""TM1 connections are private to their creator unless shared.

Revision ID: f9b3d5e7a1c2
Revises: d2f7b4e9a0c6
Create Date: 2026-10-03

Until now a connection belonged to its organization, and every member with
tm1.read could see and use it — including the owner's servers, seen by
everyone who had signed up into the same organization. A connection now has
a visibility: 'private' (only its creator, tm1_connections.created_by, can
see and use it; organization admins can see and manage it, not use it) or
'organization' (every member with the right permission, as before).

Existing connections become 'private', owned by whoever created them
(created_by is required, so every row has an owner): the leak stops the
moment this runs, and an owner who wants a colleague to keep using a
connection shares it explicitly.
"""

import sqlalchemy as sa
from alembic import op

revision = "f9b3d5e7a1c2"
down_revision = "d2f7b4e9a0c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tm1_connections",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
    )
    op.create_check_constraint(
        "ck_tm1_connections_visibility",
        "tm1_connections",
        "visibility IN ('private', 'organization')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tm1_connections_visibility", "tm1_connections", type_="check")
    op.drop_column("tm1_connections", "visibility")
