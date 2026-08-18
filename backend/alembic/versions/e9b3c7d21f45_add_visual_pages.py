"""add visual_pages for visual (ColPali) RAG

Revision ID: e9b3c7d21f45
Revises: c4f1a8b39e02
Create Date: 2026-08-18

Page images live in the object store, not here: only the reference is
stored. The embedding is a float16 blob rather than JSONB because
ColPali emits ~1030 vectors per page, which as JSONB text measures
~2.8MB per page — one 100-page document would be 273MB of a 500MB free
Postgres tier. See src/knowledge/visual/codec.py.
"""

import sqlalchemy as sa
from alembic import op

revision = "e9b3c7d21f45"
down_revision = "c4f1a8b39e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_pages",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_reference", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_vectors", sa.Integer(), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # Re-indexing replaces a document's pages rather than adding a
        # competing second set.
        sa.UniqueConstraint(
            "document_id", "page_number", name="uq_visual_page_document_page"
        ),
    )

    op.create_index(
        "ix_visual_pages_document_id", "visual_pages", ["document_id"]
    )
    op.create_index(
        "ix_visual_pages_organization_id", "visual_pages", ["organization_id"]
    )
    # The retrieval scan's exact shape: one organization, one provider.
    op.create_index(
        "ix_visual_pages_org_model",
        "visual_pages",
        ["organization_id", "embedding_model"],
    )

    # Why a document has no page images despite indexing successfully as
    # text. Not `error_message`, which means the document failed.
    op.add_column(
        "knowledge_documents",
        sa.Column("visual_index_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "visual_index_error")
    op.drop_index("ix_visual_pages_org_model", table_name="visual_pages")
    op.drop_index("ix_visual_pages_organization_id", table_name="visual_pages")
    op.drop_index("ix_visual_pages_document_id", table_name="visual_pages")
    op.drop_table("visual_pages")
