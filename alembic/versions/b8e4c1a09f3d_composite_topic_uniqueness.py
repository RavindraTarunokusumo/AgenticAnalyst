"""composite topic uniqueness for source, article, source_feed

Revision ID: b8e4c1a09f3d
Revises: 00f3ae192a5a
Create Date: 2026-07-17 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e4c1a09f3d"
down_revision: str | Sequence[str] | None = "00f3ae192a5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen uniqueness from global columns to topic-/source-scoped composites.

    - source: (topic_id, stable_id)
    - article: (topic_id, url_fingerprint)
    - source_feed: (source_id, feed_url_fingerprint)
    """
    op.drop_constraint("source_stable_id_key", "source", type_="unique")
    op.create_unique_constraint("uq_source_topic_stable_id", "source", ["topic_id", "stable_id"])

    op.drop_constraint("article_url_fingerprint_key", "article", type_="unique")
    op.create_unique_constraint(
        "uq_article_topic_url_fingerprint", "article", ["topic_id", "url_fingerprint"]
    )

    op.drop_constraint("source_feed_feed_url_fingerprint_key", "source_feed", type_="unique")
    op.create_unique_constraint(
        "uq_source_feed_source_url_fingerprint",
        "source_feed",
        ["source_id", "feed_url_fingerprint"],
    )


def downgrade() -> None:
    """Restore global uniqueness. Re-adding the global unique can fail if
    cross-topic duplicates already exist (acceptable for a downgrade path)."""
    op.drop_constraint("uq_source_feed_source_url_fingerprint", "source_feed", type_="unique")
    op.create_unique_constraint(
        "source_feed_feed_url_fingerprint_key", "source_feed", ["feed_url_fingerprint"]
    )

    op.drop_constraint("uq_article_topic_url_fingerprint", "article", type_="unique")
    op.create_unique_constraint("article_url_fingerprint_key", "article", ["url_fingerprint"])

    op.drop_constraint("uq_source_topic_stable_id", "source", type_="unique")
    op.create_unique_constraint("source_stable_id_key", "source", ["stable_id"])
