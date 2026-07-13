"""add source feed ingestion attempt and batch constraints

Revision ID: 6b135f7a55de
Revises: 963e5ab691b1
Create Date: 2026-07-13 19:46:23.439500

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b135f7a55de"
down_revision: str | Sequence[str] | None = "963e5ab691b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add RSS-to-Daily-Brief slice tables and constraints.

    - source_feed: polled RSS/Atom feeds belonging to a source.
    - ingestion_attempt: observable record of one feed/manual ingestion attempt.
    - article_batch gains batch_key (unique) and a GIN index on article_ids
      to support excluding already-batched articles from eligibility queries.
    - batch_summary gains a unique constraint on (batch_id, model, prompt_version).

    Note: article.source_id already has an FK to source.id (ON DELETE RESTRICT)
    from the initial migration; no FK addition is needed here.
    """
    op.create_table(
        "source_feed",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feed_url", sa.Text, nullable=False),
        sa.Column("feed_url_fingerprint", sa.String(length=128), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("poll_interval_minutes", sa.Integer, nullable=False),
        sa.Column("etag", sa.Text),
        sa.Column("last_modified", sa.Text),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_summary", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_source_feed_source_id", "source_feed", ["source_id"])

    op.create_table(
        "ingestion_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_feed_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_url", sa.Text, nullable=False),
        sa.Column("canonical_url", sa.Text),
        sa.Column("url_fingerprint", sa.String(length=128)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("http_status", sa.Integer),
        sa.Column("extractor", sa.String(length=32)),
        sa.Column("article_id", postgresql.UUID(as_uuid=True)),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_summary", sa.Text),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_feed_id"], ["source_feed.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ingestion_attempt_source_id", "ingestion_attempt", ["source_id"])
    op.create_index("ix_ingestion_attempt_source_feed_id", "ingestion_attempt", ["source_feed_id"])

    op.add_column("article_batch", sa.Column("batch_key", sa.String(length=256), nullable=True))
    op.execute("UPDATE article_batch SET batch_key = id::text WHERE batch_key IS NULL;")
    op.alter_column("article_batch", "batch_key", nullable=False)
    op.create_unique_constraint("uq_article_batch_batch_key", "article_batch", ["batch_key"])
    op.create_index(
        "ix_article_batch_article_ids",
        "article_batch",
        ["article_ids"],
        postgresql_using="gin",
    )

    op.create_unique_constraint(
        "uq_batch_summary_identity", "batch_summary", ["batch_id", "model", "prompt_version"]
    )


def downgrade() -> None:
    """Reverse the RSS-to-Daily-Brief slice schema additions."""
    op.drop_constraint("uq_batch_summary_identity", "batch_summary", type_="unique")

    op.drop_index("ix_article_batch_article_ids", table_name="article_batch")
    op.drop_constraint("uq_article_batch_batch_key", "article_batch", type_="unique")
    op.drop_column("article_batch", "batch_key")

    op.drop_index("ix_ingestion_attempt_source_feed_id", table_name="ingestion_attempt")
    op.drop_index("ix_ingestion_attempt_source_id", table_name="ingestion_attempt")
    op.drop_table("ingestion_attempt")

    op.drop_index("ix_source_feed_source_id", table_name="source_feed")
    op.drop_table("source_feed")
