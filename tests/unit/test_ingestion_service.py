"""Offline unit tests for IngestionService."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from analyst_engine.config import Settings
from analyst_engine.domain.models import Article, ExtractorKind, IngestionStatus, SourceFeed
from analyst_engine.ingestion.canonicalize import PrivateNetworkError
from analyst_engine.ingestion.feed_client import RetryableFeedError
from analyst_engine.ingestion.models import ExtractedArticle, FeedFetchResult
from analyst_engine.ingestion.service import IngestionService

_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")
_FEED_ID = UUID("00000000-0000-0000-0000-000000000002")
_ARTICLE_URL = "https://93.184.216.34/article.html"
_MIN_CONTENT = "x" * 250


def _settings() -> Settings:
    return Settings(
        dashscope_api_key="test-key",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        article_min_content_length=200,
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
    title: str = "Valid Title",
    published_at: datetime | None = datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
) -> ExtractedArticle:
    return ExtractedArticle(
        url=_ARTICLE_URL,
        title=title,
        text=_MIN_CONTENT,
        language="en",
        extractor=ExtractorKind.PRIMARY_HTTP,
        raw_content_hash="hash",
        published_at=published_at,
        author="Author Name",
    )


def _rss_bytes(*, links: list[str] | None = None) -> bytes:
    urls = links or [_ARTICLE_URL]
    items = "\n".join(
        f"""
        <item>
          <title>Feed Item {index}</title>
          <link>{url}</link>
          <pubDate>Thu, 10 Jul 2026 08:00:00 GMT</pubDate>
        </item>
        """
        for index, url in enumerate(urls, start=1)
    )
    return f"""<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        {items}
      </channel>
    </rss>
    """.encode()


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


class _ServiceHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.upserted_feeds: list[SourceFeed] = []
        self.saved_articles: list[Article] = []
        self.recorded_attempts: list[Any] = []
        self.fingerprint_articles: dict[str, Article] = {}
        self.ingest_side_effects: list[Exception | None] = []

        @asynccontextmanager
        async def fake_session_scope(_factory: object) -> Any:
            yield object()

        async def fake_upsert(_session: object, feed: SourceFeed) -> SourceFeed:
            self.upserted_feeds.append(feed)
            return feed

        async def fake_get_article(_session: object, fingerprint: str) -> Article | None:
            return self.fingerprint_articles.get(fingerprint)

        async def fake_save_article(_session: object, article: Article) -> Article:
            self.saved_articles.append(article)
            return article

        async def fake_record_attempt(_session: object, attempt: Any) -> Any:
            self.recorded_attempts.append(attempt)
            return attempt

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

    def build_service(
        self,
        *,
        feed_client: _FakeFeedClient,
        primary: _FakeExtractor,
        fallback: _FakeExtractor,
    ) -> IngestionService:
        return IngestionService(
            session_factory=AsyncMock(),
            feed_client=feed_client,  # type: ignore[arg-type]
            primary_extractor=primary,
            fallback_extractor=fallback,
            settings=_settings(),
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
            text=_MIN_CONTENT,
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

    results = await service.ingest_urls(_SOURCE_ID, [_ARTICLE_URL])

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
        source_id=_SOURCE_ID,
        url=_ARTICLE_URL,
        url_fingerprint="placeholder",
        title="Existing",
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
    )

    async def fake_get_article(_session: object, fingerprint: str) -> Article | None:
        return Article(
            id=existing_id,
            source_id=_SOURCE_ID,
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

    results = await service.ingest_urls(_SOURCE_ID, [_ARTICLE_URL])

    assert len(results) == 1
    assert results[0].status is IngestionStatus.DUPLICATE
    assert results[0].article_id == existing_id
    assert primary.calls == []
    assert fallback.calls == []


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

    async def flaky_ingest(candidate: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated unexpected bug")
        return await original_ingest(candidate)

    monkeypatch.setattr(service, "_ingest_candidate", flaky_ingest)

    results = await service.poll_feed(feed)

    assert len(results) == 2
    assert results[0].status is IngestionStatus.FAILED
    assert results[0].error_code == "unexpected_error"
    assert results[1].status is IngestionStatus.SUCCEEDED
