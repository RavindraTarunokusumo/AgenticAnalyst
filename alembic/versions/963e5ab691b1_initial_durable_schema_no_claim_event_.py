"""initial durable schema (no claim_event) + langgraph checkpoints

Revision ID: 963e5ab691b1
Revises:
Create Date: 2026-07-10 23:17:50.395547

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

# pgvector support for embedding vectors (available via project deps)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "963e5ab691b1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial harness schema.

    Includes:
    - Core analytical records (source, article, batch, summary, brief,
      narrative, expectation, embedding, run)
    - LangGraph checkpoint tables (checkpoints, blobs, writes, migrations)
    - No claim_event table (explicitly deferred)
    """
    # Ensure pgvector extension for embeddings
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # --- Core tables ---

    op.create_table(
        "source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("stable_id", sa.String(length=256), nullable=False, unique=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("normalized_domain", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "article",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_fingerprint", sa.String(length=128), nullable=False, unique=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("author", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("language", sa.String(length=16)),
        sa.Column("raw_content_hash", sa.String(length=128)),
        sa.Column("cleaned_content", sa.Text),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_article_source_id", "article", ["source_id"])
    op.create_index("ix_article_published_at", "article", ["published_at"])

    op.create_table(
        "article_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("grouping_method", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("similarity_threshold", sa.Float),
        sa.Column("grouping_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_article_batch_created_at", "article_batch", ["created_at"])

    op.create_table(
        "batch_summary",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("source_notes", sa.Text),
        sa.Column("entities", postgresql.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("topics", postgresql.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("citations", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["article_batch.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_batch_summary_batch_id", "batch_summary", ["batch_id"])
    op.create_index("ix_batch_summary_created_at", "batch_summary", ["created_at"])

    op.create_table(
        "narrative_state_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("change_log", postgresql.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_narrative_parent", "narrative_state_version", ["parent_id"])

    op.create_table(
        "prediction_expectation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("narrative_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("confirmation_criteria", sa.Text, nullable=False),
        sa.Column("falsification_criteria", sa.Text, nullable=False),
        sa.Column("outcome_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["narrative_version_id"], ["narrative_state_version.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "brief",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("covered_start", sa.Date, nullable=False),
        sa.Column("covered_end", sa.Date, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "cited_batch_summary_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column(
            "cited_article_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False
        ),
        sa.Column("narrative_state_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_brief_cadence_interval",
        "brief",
        ["cadence", "covered_start", "covered_end"],
        unique=True,
    )
    op.create_index("ix_brief_created_at", "brief", ["created_at"])

    op.create_table(
        "embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("vector", Vector(1536), nullable=False),
        sa.Column("metadata", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["brief_id"], ["brief.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_embedding_brief_id", "embedding", ["brief_id"])

    op.create_table(
        "workflow_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("checkpoint_ref", sa.Text),
        sa.Column("error_summary", sa.Text),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_workflow_run_cadence", "workflow_run", ["cadence"])
    op.create_index("ix_workflow_run_started_at", "workflow_run", ["started_at"])

    # --- LangGraph checkpoint tables (from langgraph-checkpoint-postgres) ---

    op.execute(
        """CREATE TABLE IF NOT EXISTS checkpoint_migrations (
            v INTEGER PRIMARY KEY
        );"""
    )

    op.execute(
        """CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        );"""
    )

    op.execute(
        """CREATE TABLE IF NOT EXISTS checkpoint_blobs (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL,
            version TEXT NOT NULL,
            type TEXT NOT NULL,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        );"""
    )

    op.execute(
        """CREATE TABLE IF NOT EXISTS checkpoint_writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            blob BYTEA NOT NULL,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        );"""
    )

    # Follow-up adjustments / indexes that the package applies
    op.execute("ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP NOT NULL;")
    op.execute("SELECT 1;")  # no-op placeholder for migration version accounting
    op.execute("CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx "
        "ON checkpoint_writes(thread_id);"
    )
    op.execute(
        "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';"
    )


def downgrade() -> None:
    """Reverse the initial schema (drops in dependency-safe order)."""
    # Drop checkpoint tables first (no FKs to our data)
    op.execute("DROP TABLE IF EXISTS checkpoint_writes;")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs;")
    op.execute("DROP TABLE IF EXISTS checkpoints;")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations;")

    op.drop_table("embedding")
    op.drop_table("workflow_run")
    op.drop_table("brief")
    op.drop_table("prediction_expectation")
    op.drop_table("narrative_state_version")
    op.drop_table("batch_summary")
    op.drop_table("article_batch")
    op.drop_table("article")
    op.drop_table("source")

    # Extension left in place (safe; other objects may depend in future)
