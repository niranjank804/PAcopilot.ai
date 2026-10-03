"""Process runs as changes, and fuller tool-execution audit.

Revision ID: c7e2a9f14b3d
Revises: e5a0c3b7d912
Create Date: 2026-09-24

tm1_changes.execution_result holds what TM1 reported for an approved
`run_process` change: success, TM1's status, the error-log file and an
excerpt, duration. It is separate from previous_content because a run has
no snapshot — nothing to restore — and conflating the two would let a
rollback path mistake a run's result for a baseline.

ai_tool_executions gains the agent that made the call and the request id
that ties the call to the HTTP request and its log lines. Both nullable:
rows written before this migration have neither.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e2a9f14b3d"
down_revision = "e5a0c3b7d912"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tm1_changes",
        sa.Column("execution_result", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "ai_tool_executions",
        sa.Column("agent", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "ai_tool_executions",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_ai_tool_executions_request_id",
        "ai_tool_executions",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_tool_executions_request_id", table_name="ai_tool_executions")
    op.drop_column("ai_tool_executions", "request_id")
    op.drop_column("ai_tool_executions", "agent")
    op.drop_column("tm1_changes", "execution_result")
