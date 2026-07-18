"""Offline unit tests for IngestionService."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from analyst_engine.config import Settings
from analyst_engine.domain.models import (
    Article,
    ExtractorKind,
    IngestionStatus,
    Source,
    SourceFeed,
    Topic,
)
from analyst_engine.ingestion.canonicalize import PrivateNetworkError
from analyst_engine.ingestion.feed_client import RetryableFeedError
from analyst_engine.ingestion.file_extractor import FileExtractionError
from analyst_engine.ingestion.models import ExtractedArticle, FeedFetchResult
from analyst_engine.ingestion.service import RELEVANCE_REJECTED_ERROR_CODE, IngestionService
from analyst_engine.topics.matcher import matches

_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_TOPIC_ID = UUID("00000000-0000-0000-0000-000000000099")
_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")
_FEED_ID = UUID("00000000-0000-0000-0000-000000000002")
_ARTICLE_URL = "https://93.184.216.34/article.html"
_MIN_CONTENT = "x" * 250
_TOPIC_KEYWORDS = ["iran", "tehran", "nuclear"]


def _settings() -> Settings:
    return Settings(
        dashscope_api_key="test-key",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        article_min_content_length=200,
    )


def _topic(*, keywords: list[str] | None = None) -> Topic:
    return Topic(
        id=_TOPIC_ID,
        name="US-Iran war",
        description="Follow the conflict",
        keywords=keywords if keywords is not None else list(_TOPIC_KEYWORDS),
    )


def _source() -> Source:
    return Source(
        id=_SOURCE_ID,
        topic_id=_TOPIC_ID,
        stable_id="reuters",
        name="Reuters",
        normalized_domain="reuters.com",
    )


def _feed() -> SourceFeed:
    return SourceFeed(
        id=_FEED_ID,
        source_id=_SOURCE_ID,
        feed_url="https://93.184.216.34/feed.xml",
        feed_url_fingerprint="feed-fingerprint",
        poll_interval_minutes=60,
        etag='"etag-1"',
        last_modified="Thu, 10 Jul 2026 08:00:00 GMT",
    )


def _valid_extracted(
    *,
    title: str = "Iran nuclear talks resume",
    text: str = _MIN_CONTENT + " Iran nuclear talks in Geneva continue.",
    published_at: datetime | None = datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
) -> ExtractedArticle:
    return ExtractedArticle(
        url=_ARTICLE_URL,
        title=title,
        text=text,
        language="en",
        extractor=ExtractorKind.PRIMARY_HTTP,
        raw_content_hash="hash",
        published_at=published_at,
        author="Author Name",
    )


def _rss_bytes(
    *,
    items: list[tuple[str, str, str | None]] | None = None,
    links: list[str] | None = None,
) -> bytes:
    """Build RSS bytes.

    ``items`` is a list of (title, url, description|None). When omitted,
    ``links`` (or the default article URL) produce generic on-topic titles.
    """
    if items is None:
        urls = links or [_ARTICLE_URL]
        items = [(f"Iran update {index}", url, None) for index, url in enumerate(urls, start=1)]

    item_xml = []
    for title, url, description in items:
        desc_tag = (
            f"<description>{escape(description)}</description>" if description is not None else ""
        )
        item_xml.append(
            f"""
        <item>
          <title>{escape(title)}</title>
          <link>{escape(url)}</link>
          {desc_tag}
          <pubDate>Thu, 10 Jul 2026 08:00:00 GMT</pubDate>
        </item>
        """
        )
    return f"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        {"".join(item_xml)}
      </channel>
    </rss>
    """.encode()


def _always_relevant(_keywords: list[str], *fields: str | None) -> bool:
    """Default harness predicate: admit every candidate (existing-path tests)."""
    del _keywords, fields
    return True


class _FakeFeedClient:
    def __init__(self, result: FeedFetchResult | Exception) -> None:
        self._result = result
        self.calls: list[tuple[str, str | None, str | None]] = []

    async def fetch(
        self,
        feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult:
        self.calls.append((feed_url, etag, last_modified))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeExtractor:
    def __init__(self, result: ExtractedArticle | Exception) -> None:
        self._result = result
        self.calls: list[str] = []

    async def extract(self, url: str) -> ExtractedArticle:
        self.calls.append(url)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeFileExtractor:
    def __init__(self, result: ExtractedArticle | Exception) -> None:
        self._result = result
        self.calls: list[tuple[str, bytes]] = []

    def extract(self, filename: str, content: bytes) -> ExtractedArticle:
        self.calls.append((filename, content))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _ServiceHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.upserted_feeds: list[SourceFeed] = []
        self.saved_articles: list[Article] = []
        self.recorded_attempts: list[Any] = []
        self.fingerprint_articles: dict[str, Article] = {}
        self.ingest_side_effects: list[Exception | None] = []
        self.topic = _topic()
        self.source = _source()

        @asynccontextmanager
        async def fake_session_scope(_factory: object) -> Any:
            yield object()

        async def fake_upsert(_session: object, feed: SourceFeed) -> SourceFeed:
            self.upserted_feeds.append(feed)
            return feed

        async def fake_get_article(
            _session: object, fingerprint: str, *, topic_id: UUID
        ) -> Article | None:
            return self.fingerprint_articles.get(fingerprint)

        async def fake_save_article(_session: object, article: Article) -> Article:
            self.saved_articles.append(article)
            return article

        async def fake_record_attempt(_session: object, attempt: Any) -> Any:
            self.recorded_attempts.append(attempt)
            return attempt

        async def fake_get_sources(_session: object, source_ids: list[UUID]) -> list[Source]:
            if self.source.id in source_ids:
                return [self.source]
            return []

        async def fake_get_topic(_session: object, topic_id: UUID) -> Topic | None:
            if topic_id == self.topic.id:
                return self.topic
            return None

        monkeypatch.setattr("analyst_engine.ingestion.service.session_scope", fake_session_scope)
        monkeypatch.setattr("analyst_engine.ingestion.service.upsert_source_feed", fake_upsert)
        monkeypatch.setattr(
            "analyst_engine.ingestion.service.get_article_by_fingerprint",
            fake_get_article,
        )
        monkeypatch.setattr("analyst_engine.ingestion.service.save_article", fake_save_article)
        monkeypatch.setattr(
            "analyst_engine.ingestion.service.record_ingestion_attempt",
            fake_record_attempt,
        )
        monkeypatch.setattr(
            "analyst_engine.ingestion.service.get_sources_by_ids",
            fake_get_sources,
        )
        monkeypatch.setattr("analyst_engine.ingestion.service.get_topic", fake_get_topic)

    def build_service(
        self,
        *,
        feed_client: _FakeFeedClient,
        primary: _FakeExtractor,
        fallback: _FakeExtractor,
        file_extractors: dict[str, Any] | None = None,
        is_relevant: Any = _always_relevant,
    ) -> IngestionService:
        return IngestionService(
            session_factory=AsyncMock(),
            feed_client=feed_client,  # type: ignore[arg-type]
            primary_extractor=primary,
            fallback_extractor=fallback,
            settings=_settings(),
            file_extractors=file_extractors or {},
            is_relevant=is_relevant,
            clock=lambda: _FIXED_NOW,
        )


@pytest.mark.asyncio
async def test_poll_feed_success_records_succeeded_result_and_updates_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag='"etag-2"',
        last_modified="Thu, 11 Jul 2026 08:00:00 GMT",
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(),
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
    )

    results = await service.poll_feed(feed)

    assert len(results) == 1
    assert results[0].status is IngestionStatus.SUCCEEDED
    assert results[0].article_id is not None
    assert len(harness.upserted_feeds) == 1
    updated = harness.upserted_feeds[0]
    assert updated.last_polled_at == _FIXED_NOW
    assert updated.last_success_at == _FIXED_NOW
    assert updated.last_error_summary is None
    assert updated.etag == '"etag-2"'
    assert updated.last_modified == "Thu, 11 Jul 2026 08:00:00 GMT"
    assert harness.saved_articles[0].topic_id == _TOPIC_ID
    assert harness.saved_articles[0].source_id == _SOURCE_ID


@pytest.mark.asyncio
async def test_poll_feed_fetch_failure_updates_feed_error_without_candidate_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    service = harness.build_service(
        feed_client=_FakeFeedClient(RetryableFeedError("upstream timeout")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
    )

    results = await service.poll_feed(feed)

    assert results == []
    assert len(harness.upserted_feeds) == 1
    updated = harness.upserted_feeds[0]
    assert updated.last_polled_at == _FIXED_NOW
    assert updated.last_error_summary == "RetryableFeedError: upstream timeout"
    assert updated.last_success_at is None
    assert updated.etag == feed.etag


@pytest.mark.asyncio
async def test_poll_feed_not_modified_updates_success_without_changing_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=304,
        not_modified=True,
        etag='"new-etag-ignored"',
        last_modified="Thu, 12 Jul 2026 08:00:00 GMT",
        final_url=feed.feed_url,
        raw_bytes=None,
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
    )

    results = await service.poll_feed(feed)

    assert results == []
    updated = harness.upserted_feeds[0]
    assert updated.last_polled_at == _FIXED_NOW
    assert updated.last_success_at == _FIXED_NOW
    assert updated.last_error_summary is None
    assert updated.etag == feed.etag
    assert updated.last_modified == feed.last_modified


@pytest.mark.asyncio
async def test_poll_feed_uses_fallback_when_primary_extraction_is_inadequate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(),
    )
    primary = _FakeExtractor(
        ExtractedArticle(
            url=_ARTICLE_URL,
            title="Short",
            text="too short",
            language="en",
            extractor=ExtractorKind.PRIMARY_HTTP,
            raw_content_hash="primary",
            published_at=datetime(2026, 7, 10, tzinfo=UTC),
            author=None,
        )
    )
    fallback = _FakeExtractor(
        ExtractedArticle(
            url=_ARTICLE_URL,
            title="Fallback Title",
            text=_MIN_CONTENT + " Iran nuclear talks continue.",
            language="en",
            extractor=ExtractorKind.CRAWL4AI,
            raw_content_hash="fallback",
            published_at=datetime(2026, 7, 10, tzinfo=UTC),
            author=None,
        )
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=fallback,
    )

    results = await service.poll_feed(feed)

    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert results[0].status is IngestionStatus.SUCCEEDED
    assert harness.saved_articles[0].title == "Fallback Title"


@pytest.mark.asyncio
async def test_poll_feed_ssrf_rejection_from_primary_is_terminal_and_skips_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PrivateNetworkError from the primary extractor (e.g. a redirect that
    resolves to a private/loopback address) must be terminal. Falling back to
    Crawl4AI - which performs no host or redirect validation of its own -
    would turn a blocked SSRF attempt into a successful one via the weaker
    path, so the fallback extractor must never be invoked in this case.
    """
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(),
    )
    primary = _FakeExtractor(PrivateNetworkError("host resolves to restricted address: 127.0.0.1"))
    fallback = _FakeExtractor(_valid_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=fallback,
    )

    results = await service.poll_feed(feed)

    assert len(primary.calls) == 1
    assert fallback.calls == []
    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == "invalid_url"


@pytest.mark.asyncio
async def test_poll_feed_missing_title_fails_with_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(),
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=_FakeExtractor(_valid_extracted(title="   ")),
        fallback=_FakeExtractor(_valid_extracted(title="   ")),
    )

    results = await service.poll_feed(feed)

    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == "missing_title"


@pytest.mark.asyncio
async def test_poll_feed_stage1_rejects_without_fetching_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 1 (title+summary) rejection must never call the article extractor."""
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    off_topic_url = "https://93.184.216.34/sports.html"
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(
            items=[("Premier League table update", off_topic_url, "Scores and fixtures")]
        ),
    )
    primary = _FakeExtractor(_valid_extracted())
    fallback = _FakeExtractor(_valid_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=fallback,
        is_relevant=matches,
    )

    results = await service.poll_feed(feed)

    assert len(results) == 1
    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == RELEVANCE_REJECTED_ERROR_CODE
    assert primary.calls == []
    assert fallback.calls == []
    assert harness.saved_articles == []
    assert len(harness.recorded_attempts) == 1
    attempt = harness.recorded_attempts[0]
    assert attempt.error_code == RELEVANCE_REJECTED_ERROR_CODE
    assert attempt.topic_id == _TOPIC_ID
    assert attempt.source_id == _SOURCE_ID
    assert attempt.status is IngestionStatus.FAILED


@pytest.mark.asyncio
async def test_poll_feed_stage1_admits_summary_keyword_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vague titles still pass stage 1 when the feed summary carries a keyword."""
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(
            items=[
                (
                    "Talks collapse in Geneva",
                    _ARTICLE_URL,
                    "Tehran rejects the latest nuclear proposal",
                )
            ]
        ),
    )
    primary = _FakeExtractor(_valid_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=_FakeExtractor(_valid_extracted()),
        is_relevant=matches,
    )

    results = await service.poll_feed(feed)

    assert results[0].status is IngestionStatus.SUCCEEDED
    assert primary.calls == [_ARTICLE_URL]
    assert harness.saved_articles[0].topic_id == _TOPIC_ID


@pytest.mark.asyncio
async def test_poll_feed_stage2_rejects_after_extraction_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 2 drops headline matches whose extracted body is off-topic."""
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(items=[("Iran market opens higher", _ARTICLE_URL, None)]),
    )
    # Body never mentions any topic keyword — precision drop.
    off_topic_body = _MIN_CONTENT + " Local equities rose on retail earnings."
    primary = _FakeExtractor(
        _valid_extracted(title="Iran market opens higher", text=off_topic_body)
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=_FakeExtractor(_valid_extracted()),
        is_relevant=matches,
    )

    results = await service.poll_feed(feed)

    assert len(primary.calls) == 1
    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == RELEVANCE_REJECTED_ERROR_CODE
    assert harness.saved_articles == []
    assert len(harness.recorded_attempts) == 1
    assert harness.recorded_attempts[0].error_code == RELEVANCE_REJECTED_ERROR_CODE
    assert harness.recorded_attempts[0].topic_id == _TOPIC_ID


@pytest.mark.asyncio
async def test_poll_feed_on_topic_article_passes_both_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(items=[("Iran nuclear talks resume in Geneva", _ARTICLE_URL, None)]),
    )
    primary = _FakeExtractor(_valid_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=primary,
        fallback=_FakeExtractor(_valid_extracted()),
        is_relevant=matches,
    )

    results = await service.poll_feed(feed)

    assert results[0].status is IngestionStatus.SUCCEEDED
    assert primary.calls == [_ARTICLE_URL]
    assert len(harness.saved_articles) == 1
    assert harness.saved_articles[0].topic_id == _TOPIC_ID
    assert harness.saved_articles[0].source_id == _SOURCE_ID
    assert harness.recorded_attempts[0].status is IngestionStatus.SUCCEEDED
    assert harness.recorded_attempts[0].topic_id == _TOPIC_ID


@pytest.mark.asyncio
async def test_ingest_urls_missing_published_at_fails_with_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    extracted = _valid_extracted(published_at=None)
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, _ARTICLE_URL, b"")),
        primary=_FakeExtractor(extracted),
        fallback=_FakeExtractor(extracted),
    )

    results = await service.ingest_urls(_TOPIC_ID, [_ARTICLE_URL])

    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == "missing_published_at"


@pytest.mark.asyncio
async def test_ingest_urls_duplicate_short_circuits_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    existing_id = uuid4()
    harness.fingerprint_articles["will-be-set-by-canonicalize"] = Article(
        id=existing_id,
        topic_id=_TOPIC_ID,
        source_id=None,
        url=_ARTICLE_URL,
        url_fingerprint="placeholder",
        title="Existing",
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
    )

    async def fake_get_article(
        _session: object, fingerprint: str, *, topic_id: UUID
    ) -> Article | None:
        return Article(
            id=existing_id,
            topic_id=_TOPIC_ID,
            source_id=None,
            url=_ARTICLE_URL,
            url_fingerprint=fingerprint,
            title="Existing",
            published_at=datetime(2026, 7, 10, tzinfo=UTC),
        )

    monkeypatch.setattr(
        "analyst_engine.ingestion.service.get_article_by_fingerprint",
        fake_get_article,
    )

    primary = _FakeExtractor(_valid_extracted())
    fallback = _FakeExtractor(_valid_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, _ARTICLE_URL, b"")),
        primary=primary,
        fallback=fallback,
    )

    results = await service.ingest_urls(_TOPIC_ID, [_ARTICLE_URL])

    assert len(results) == 1
    assert results[0].status is IngestionStatus.DUPLICATE
    assert results[0].article_id == existing_id
    assert primary.calls == []
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_ingest_urls_sets_topic_id_with_source_id_none_and_skips_relevance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct URL adds are never relevance-filtered (user chose the article)."""
    harness = _ServiceHarness(monkeypatch)
    # Body has no topic keywords; if filtered this would fail stage 2.
    off_topic = _valid_extracted(
        title="Local sports roundup",
        text=_MIN_CONTENT + " Basketball scores and fixtures.",
    )
    primary = _FakeExtractor(off_topic)
    relevance_calls: list[tuple[Any, ...]] = []

    def tracking_relevant(keywords: list[str], *fields: str | None) -> bool:
        relevance_calls.append((keywords, fields))
        return False

    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, _ARTICLE_URL, b"")),
        primary=primary,
        fallback=_FakeExtractor(off_topic),
        is_relevant=tracking_relevant,
    )

    results = await service.ingest_urls(_TOPIC_ID, [_ARTICLE_URL])

    assert results[0].status is IngestionStatus.SUCCEEDED
    assert len(harness.saved_articles) == 1
    article = harness.saved_articles[0]
    assert article.topic_id == _TOPIC_ID
    assert article.source_id is None
    assert relevance_calls == []
    assert primary.calls == [_ARTICLE_URL]


@pytest.mark.asyncio
async def test_poll_feed_continues_after_unexpected_candidate_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    feed = _feed()
    urls = [
        "https://93.184.216.34/first.html",
        "https://93.184.216.34/second.html",
    ]
    fetch_result = FeedFetchResult(
        status_code=200,
        not_modified=False,
        etag=None,
        last_modified=None,
        final_url=feed.feed_url,
        raw_bytes=_rss_bytes(links=urls),
    )
    service = harness.build_service(
        feed_client=_FakeFeedClient(fetch_result),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
    )

    original_ingest = service._ingest_candidate
    call_count = 0

    async def flaky_ingest(candidate: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated unexpected bug")
        return await original_ingest(candidate, **kwargs)

    monkeypatch.setattr(service, "_ingest_candidate", flaky_ingest)

    results = await service.poll_feed(feed)

    assert len(results) == 2
    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == "unexpected_error"
    assert results[1].status is IngestionStatus.SUCCEEDED


def _file_extracted(
    *,
    title: str = "Uploaded Title",
    text: str = _MIN_CONTENT,
    published_at: datetime | None = None,
) -> ExtractedArticle:
    return ExtractedArticle(
        url="report.pdf",
        title=title,
        text=text,
        language=None,
        extractor=ExtractorKind.FILE_PDF,
        raw_content_hash="hash",
        published_at=published_at,
        author=None,
    )


@pytest.mark.asyncio
async def test_ingest_file_oversized_content_fails_with_error_code_and_records_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    extractor = _FakeFileExtractor(_file_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": extractor},
    )
    oversized_content = b"x" * (_settings().article_max_response_size_bytes + 1)

    result = await service.ingest_file(_TOPIC_ID, "big.pdf", oversized_content, "application/pdf")

    assert result.status is IngestionStatus.FAILED
    assert result.error_code == "file_too_large"
    assert extractor.calls == []
    assert len(harness.recorded_attempts) == 1
    assert harness.recorded_attempts[0].error_code == "file_too_large"
    assert harness.recorded_attempts[0].topic_id == _TOPIC_ID
    assert harness.recorded_attempts[0].source_id is None


@pytest.mark.asyncio
async def test_ingest_file_success_stamps_ingestion_time_as_published_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    content = b"uploaded pdf bytes"
    extractor = _FakeFileExtractor(_file_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": extractor},
    )

    result = await service.ingest_file(_TOPIC_ID, "report.pdf", content, "application/pdf")

    assert result.status is IngestionStatus.SUCCEEDED
    assert result.candidate_url == f"upload://{hashlib.sha256(content).hexdigest()}"
    assert extractor.calls == [("report.pdf", content)]
    assert len(harness.saved_articles) == 1
    assert harness.saved_articles[0].published_at == _FIXED_NOW
    assert harness.saved_articles[0].topic_id == _TOPIC_ID
    assert harness.saved_articles[0].source_id is None


@pytest.mark.asyncio
async def test_ingest_file_sets_topic_id_source_id_none_and_skips_relevance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    content = b"uploaded pdf bytes"
    # Content has no topic keywords; filter would reject if applied.
    extractor = _FakeFileExtractor(
        _file_extracted(title="Sports report", text=_MIN_CONTENT + " Basketball results.")
    )
    relevance_calls: list[tuple[Any, ...]] = []

    def tracking_relevant(keywords: list[str], *fields: str | None) -> bool:
        relevance_calls.append((keywords, fields))
        return False

    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": extractor},
        is_relevant=tracking_relevant,
    )

    result = await service.ingest_file(_TOPIC_ID, "report.pdf", content, "application/pdf")

    assert result.status is IngestionStatus.SUCCEEDED
    article = harness.saved_articles[0]
    assert article.topic_id == _TOPIC_ID
    assert article.source_id is None
    assert relevance_calls == []


@pytest.mark.asyncio
async def test_ingest_file_duplicate_short_circuits_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    content = b"already ingested bytes"
    content_hash = hashlib.sha256(content).hexdigest()
    existing_id = uuid4()
    harness.fingerprint_articles[content_hash] = Article(
        id=existing_id,
        topic_id=_TOPIC_ID,
        source_id=None,
        url=f"upload://{content_hash}",
        url_fingerprint=content_hash,
        title="Existing",
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    extractor = _FakeFileExtractor(_file_extracted())
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": extractor},
    )

    result = await service.ingest_file(_TOPIC_ID, "report.pdf", content, "application/pdf")

    assert result.status is IngestionStatus.DUPLICATE
    assert result.article_id == existing_id
    assert extractor.calls == []


@pytest.mark.asyncio
async def test_ingest_file_unsupported_content_type_fails_with_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": _FakeFileExtractor(_file_extracted())},
    )

    result = await service.ingest_file(_TOPIC_ID, "notes.docx", b"bytes", "application/msword")

    assert result.status is IngestionStatus.FAILED
    assert result.error_code == "unsupported_file_type"


@pytest.mark.asyncio
async def test_ingest_file_extraction_error_fails_with_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _ServiceHarness(monkeypatch)
    extractor = _FakeFileExtractor(FileExtractionError("no extractable text"))
    service = harness.build_service(
        feed_client=_FakeFeedClient(FeedFetchResult(200, False, None, None, "", b"")),
        primary=_FakeExtractor(_valid_extracted()),
        fallback=_FakeExtractor(_valid_extracted()),
        file_extractors={"application/pdf": extractor},
    )

    result = await service.ingest_file(_TOPIC_ID, "blank.pdf", b"bytes", "application/pdf")

    assert result.status is IngestionStatus.FAILED
    assert result.error_code == "extraction_failed"
