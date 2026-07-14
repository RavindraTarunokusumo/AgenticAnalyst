"""Pure value objects for feed ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from analyst_engine.domain.models import ExtractorKind


@dataclass(frozen=True)
class FeedFetchResult:
    status_code: int
    not_modified: bool
    etag: str | None
    last_modified: str | None
    final_url: str
    raw_bytes: bytes | None


@dataclass(frozen=True)
class ArticleCandidate:
    source_id: UUID
    source_feed_id: UUID | None
    url: str
    title: str | None
    author: str | None
    published_at: datetime | None
    entry_id: str | None


@dataclass(frozen=True)
class CleanedContent:
    title: str | None
    text: str
    language: str | None


@dataclass(frozen=True)
class ExtractedArticle:
    url: str
    title: str | None
    text: str
    language: str | None
    extractor: ExtractorKind
    raw_content_hash: str
