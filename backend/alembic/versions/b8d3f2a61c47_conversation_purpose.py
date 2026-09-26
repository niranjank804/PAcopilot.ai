"""Mark conversations the product starts for itself.

Revision ID: b8d3f2a61c47
Revises: a3d7e91c40b2
Create Date: 2026-09-26

Visualize runs the Analyst agent through the chat orchestrator, which
records a conversation. Those conversations appeared in each user's Chat
history, showing the internal instructions as if the user had typed them.

They cannot simply be deleted: ai_usage rows cascade with their
conversation, so deleting one would erase what the request cost and hand
it back to the monthly quota. Instead they carry a purpose, and the history
list leaves them out.

The upgrade also marks the ones already created, identified by the prompt
src/ai/visualization.py sends — "Use connection_id=… Visualization
request: …" — which no person types.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8d3f2a61c47"
down_revision = "a3d7e91c40b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column("purpose", sa.String(length=20), nullable=True),
    )
    op.execute(
        """
        UPDATE ai_conversations
        SET purpose = 'visualize'
        WHERE id IN (
            SELECT conversation_id FROM ai_messages
            WHERE role = 'user'
              AND content LIKE 'Use connection_id=%'
              AND content LIKE '%Visualization request:%'
        )
        """
    )


def downgrade() -> None:
    op.drop_column("ai_conversations", "purpose")
