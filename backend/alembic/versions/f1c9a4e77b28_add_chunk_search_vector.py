"""add a full-text search vector to knowledge_chunks

Revision ID: f1c9a4e77b28
Revises: e9b3c7d21f45
Create Date: 2026-09-15

Embeddings were the *only* way to reach a chunk, which made the whole
Knowledge Base a single point of failure on one external provider. That
failure has now happened twice, both times as "no credits remaining":
search and Ask die, while Chat carries on because it only needs
Anthropic — so nothing in the product signals that half of it is gone.

This column is the free fallback. Keyword search is worse than semantic
search at understanding a question, and completely unaffected by
somebody else's billing.

Two details that would break it if got wrong:

* **The expression must be the two-argument `to_tsvector`.** A generated
  column requires an IMMUTABLE expression. `to_tsvector(text)` is only
  STABLE, because it reads `default_text_search_config` at runtime;
  `to_tsvector(regconfig, text)` is IMMUTABLE. Postgres rejects the
  one-argument form outright here.

* **GIN, not GIN-on-nothing.** Without the index this is a sequential
  scan over every chunk in the deployment, which is the cost profile the
  fallback exists to avoid.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1c9a4e77b28"
down_revision = "e9b3c7d21f45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
    )

    # Tenancy is always part of the predicate, but the tsvector is the
    # selective half — an organization can hold every chunk in a
    # single-tenant deployment.
    op.create_index(
        "ix_knowledge_chunks_search_vector",
        "knowledge_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_chunks_search_vector", table_name="knowledge_chunks"
    )
    op.drop_column("knowledge_chunks", "search_vector")
