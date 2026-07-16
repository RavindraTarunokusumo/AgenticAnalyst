"""Pure RSS/Atom feed parsing into article candidates."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

import feedparser

from analyst_engine.ingestion.models import ArticleCandidate


class FeedParseError(RuntimeError):
    """Raised when a feed document is malformed and yields no usable entries."""


def _struct_time_to_datetime(struct_time: time.struct_time) -> datetime:
    return datetime(*struct_time[:6], tzinfo=UTC)


def _entry_published_at(entry: feedparser.FeedParserDict) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if published_parsed is not None:
        return _struct_time_to_datetime(published_parsed)

    updated_parsed = entry.get("updated_parsed")
    if updated_parsed is not None:
        return _struct_time_to_datetime(updated_parsed)

    return None


def _sort_key(candidate: ArticleCandidate) -> tuple[datetime, str, str]:
    return (
        candidate.published_at or datetime.min.replace(tzinfo=UTC),
        candidate.url,
        candidate.entry_id or "",
    )


def parse_feed(
    raw_bytes: bytes,
    feed_url: str,
    source_id: UUID,
    *,
    source_feed_id: UUID | None = None,
) -> list[ArticleCandidate]:
    """Parse RSS/Atom bytes into deterministically ordered article candidates."""
    del feed_url  # reserved for future diagnostics; parsing is feed-format driven

    parsed = feedparser.parse(raw_bytes)

    if parsed.bozo and len(parsed.entries) == 0:
        raise FeedParseError("feed document is malformed and contains no entries")

    candidates: list[ArticleCandidate] = []
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue

        title = entry.get("title") or None
        author = entry.get("author") or None
        published_at = _entry_published_at(entry)
        entry_id = entry.get("id") or entry.get("guid") or None
        # feedparser normalises RSS description and Atom summary onto "summary";
        # fall back to "description" for raw RSS-shaped dicts.
        summary = entry.get("summary") or entry.get("description") or None

        candidates.append(
            ArticleCandidate(
                source_id=source_id,
                source_feed_id=source_feed_id,
                url=link,
                title=title,
                author=author,
                published_at=published_at,
                entry_id=entry_id,
                summary=summary,
            )
        )

    candidates.sort(key=_sort_key)
    return candidates
