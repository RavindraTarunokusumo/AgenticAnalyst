"""add topic table and topic_id foreign keys

Revision ID: 00f3ae192a5a
Revises: 6b135f7a55de
Create Date: 2026-07-16 12:00:00.000000

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "00f3ae192a5a"
down_revision: str | Sequence[str] | None = "6b135f7a55de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Non-empty sentinel: Topic.keywords rejects empty lists, and empty would mean
# "match nothing" for the Default backfill topic. Double-underscore token is
# deliberately unlikely to match real article content.
_DEFAULT_KEYWORDS_SENTINEL = "__default__"


def upgrade() -> None:
    """Create topic, backfill Default, then enforce topic_id NOT NULL.

    Order is load-bearing: create table -> insert Default with non-empty
    keywords -> add nullable topic_id columns -> backfill existing rows ->
    only then set NOT NULL / FKs. Making article.source_id and
    ingestion_attempt.source_id nullable supports source-less direct inputs
    (pasted links / uploads; spec §3.2).
    """
    op.create_table(
        "topic",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("interest_detail", sa.Text),
        sa.Column("keywords", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    default_topic_id = str(uuid.uuid4())
    op.execute(
        f"""
        INSERT INTO topic (id, name, description, interest_detail, keywords, created_at, updated_at)
        VALUES (
            '{default_topic_id}'::uuid,
            'Default',
            'Adopts pre-existing rows from before topic-first migration',
            NULL,
            ARRAY['{_DEFAULT_KEYWORDS_SENTINEL}']::text[],
            now(),
            now()
        );
        """
    )

    for table in ("source", "article", "brief", "ingestion_attempt"):
        op.add_column(
            table,
            sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.execute(
            f"UPDATE {table} SET topic_id = '{default_topic_id}'::uuid WHERE topic_id IS NULL;"
        )
        op.alter_column(table, "topic_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_topic_id",
            table,
            "topic",
            ["topic_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_topic_id", table, ["topic_id"])

    op.alter_column(
        "article", "source_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.alter_column(
        "ingestion_attempt",
        "source_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # Briefs are one-per-topic-per-cadence-per-window (spec §4). The initial
    # schema used unique index ix_brief_cadence_interval (not a table unique
    # constraint). Replace it so two topics may brief the same date.
    op.drop_index("ix_brief_cadence_interval", table_name="brief")
    op.create_index(
        "ix_brief_topic_cadence_interval",
        "brief",
        ["topic_id", "cadence", "covered_start", "covered_end"],
        unique=True,
    )


def downgrade() -> None:
    """Reverse topic_id columns and the topic table."""
    op.drop_index("ix_brief_topic_cadence_interval", table_name="brief")
    op.create_index(
        "ix_brief_cadence_interval",
        "brief",
        ["cadence", "covered_start", "covered_end"],
        unique=True,
    )

    op.alter_column(
        "ingestion_attempt",
        "source_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "article", "source_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )

    for table in ("ingestion_attempt", "brief", "article", "source"):
        op.drop_index(f"ix_{table}_topic_id", table_name=table)
        op.drop_constraint(f"fk_{table}_topic_id", table, type_="foreignkey")
        op.drop_column(table, "topic_id")

    op.drop_table("topic")
