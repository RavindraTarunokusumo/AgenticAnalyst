"""Feed polling and URL ingestion orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.config import Settings
from analyst_engine.domain.models import Article, IngestionAttempt, IngestionStatus, SourceFeed
from analyst_engine.ingestion.canonicalize import UrlValidationError, canonicalize_url
from analyst_engine.ingestion.extractor import (
    ArticleExtractor,
    ExtractionFailedError,
    should_use_fallback,
)
from analyst_engine.ingestion.feed_client import FeedClient, RetryableFeedError, TerminalFeedError
from analyst_engine.ingestion.feed_parser import FeedParseError, parse_feed
from analyst_engine.ingestion.file_extractor import FileExtractionError, FileExtractor
from analyst_engine.ingestion.models import ArticleCandidate, ExtractedArticle, IngestionResult
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import (
    get_article_by_fingerprint,
    record_ingestion_attempt,
    save_article,
    upsert_source_feed,
)

_ERROR_SUMMARY_MAX_LENGTH = 500

# Some browser/OS mime-db combinations report an empty or generic content-type
# for a drag-and-dropped or oddly-associated file even though its extension is
# unambiguous - fall back to the extension when the reported type doesn't
# match a registered extractor, rather than rejecting a file the UI's own
# accept-list allowed.
_EXTENSION_FALLBACK_CONTENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain"}


def _sanitize_error_summary(message: str) -> str:
    cleaned = message.strip()
    if len(cleaned) > _ERROR_SUMMARY_MAX_LENGTH:
        return cleaned[:_ERROR_SUMMARY_MAX_LENGTH]
    return cleaned


def _failure_summary_from_exception(exc: Exception) -> str:
    return _sanitize_error_summary(f"{type(exc).__name__}: {exc}")


class IngestionService:
    """Coordinates feed polling, article extraction, and persistence."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        feed_client: FeedClient,
        primary_extractor: ArticleExtractor,
        fallback_extractor: ArticleExtractor,
        settings: Settings,
        file_extractors: dict[str, FileExtractor],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._feed_client = feed_client
        self._primary_extractor = primary_extractor
        self._fallback_extractor = fallback_extractor
        self._settings = settings
        self._file_extractors = file_extractors
        self._clock = clock

    async def poll_feed(self, feed: SourceFeed) -> list[IngestionResult]:
        now = self._clock()

        try:
            fetch_result = await self._feed_client.fetch(
                feed.feed_url,
                etag=feed.etag,
                last_modified=feed.last_modified,
            )
        except (RetryableFeedError, TerminalFeedError) as exc:
            await self._update_feed_on_failure(feed, now, exc)
            return []

        if fetch_result.not_modified:
            await self._update_feed_on_not_modified(feed, now)
            return []

        try:
            candidates = parse_feed(
                fetch_result.raw_bytes or b"",
                feed.feed_url,
                feed.source_id,
                source_feed_id=feed.id,
            )
        except FeedParseError as exc:
            await self._update_feed_on_failure(feed, now, exc)
            return []

        updated_feed = feed.model_copy(
            update={
                "last_polled_at": now,
                "last_success_at": now,
                "etag": fetch_result.etag or feed.etag,
                "last_modified": fetch_result.last_modified or feed.last_modified,
                "last_error_summary": None,
                "updated_at": now,
            }
        )
        async with session_scope(self._session_factory) as session:
            await upsert_source_feed(session, updated_feed)

        results: list[IngestionResult] = []
        for candidate in candidates:
            try:
                result = await self._ingest_candidate(candidate)
            except Exception:
                result = IngestionResult(
                    candidate_url=candidate.url,
                    status=IngestionStatus.FAILED,
                    article_id=None,
                    error_code="unexpected_error",
                    error_summary="unexpected error while ingesting feed candidate",
                )
            results.append(result)
        return results

    async def ingest_urls(self, source_id: UUID, urls: list[str]) -> list[IngestionResult]:
        results: list[IngestionResult] = []
        for url in urls:
            candidate = ArticleCandidate(
                source_id=source_id,
                source_feed_id=None,
                url=url,
                title=None,
                author=None,
                published_at=None,
                entry_id=None,
            )
            try:
                result = await self._ingest_candidate(candidate)
            except Exception:
                result = IngestionResult(
                    candidate_url=url,
                    status=IngestionStatus.FAILED,
                    article_id=None,
                    error_code="unexpected_error",
                    error_summary="unexpected error while ingesting URL",
                )
            results.append(result)
        return results

    async def ingest_file(
        self,
        source_id: UUID,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> IngestionResult:
        started_at = self._clock()
        content_hash = hashlib.sha256(content).hexdigest()
        url = f"upload://{content_hash}"
        candidate = ArticleCandidate(
            source_id=source_id,
            source_feed_id=None,
            url=url,
            title=None,
            author=None,
            published_at=None,
            entry_id=None,
        )

        if len(content) > self._settings.article_max_response_size_bytes:
            return await self._record_failure(
                candidate,
                url,
                content_hash,
                "file_too_large",
                (
                    f"file size {len(content)} exceeds maximum "
                    f"{self._settings.article_max_response_size_bytes} bytes"
                ),
                started_at,
            )

        duplicate_result = await self._check_duplicate(candidate, url, content_hash, started_at)
        if duplicate_result is not None:
            return duplicate_result

        extractor = self._file_extractors.get(content_type)
        if extractor is None:
            fallback_type = _EXTENSION_FALLBACK_CONTENT_TYPES.get(Path(filename).suffix.lower())
            if fallback_type is not None:
                extractor = self._file_extractors.get(fallback_type)
        if extractor is None:
            return await self._record_failure(
                candidate,
                url,
                content_hash,
                "unsupported_file_type",
                f"unsupported content type: {content_type}",
                started_at,
            )

        try:
            extracted = extractor.extract(filename, content)
        except FileExtractionError as exc:
            return await self._record_failure(
                candidate,
                url,
                content_hash,
                "extraction_failed",
                str(exc),
                started_at,
            )
        except Exception as exc:
            # Malformed input can make pypdf raise something other than its own
            # PyPdfError (KeyError/AttributeError/ValueError observed against
            # fuzzed PDFs) - mirrors _ingest_candidate's broad `except Exception`
            # around extraction (service.py primary/fallback path) rather than
            # enumerating extractor-internal exception types here.
            return await self._record_failure(
                candidate,
                url,
                content_hash,
                "extraction_failed",
                _failure_summary_from_exception(exc),
                started_at,
            )

        # Uploaded files carry no publish-date metadata (spec §4.1); the
        # extractor has no clock, so ingest_file stamps ingestion time here.
        if extracted.published_at is None:
            extracted = replace(extracted, published_at=self._clock())

        return await self._finalize_extracted(candidate, url, content_hash, extracted, started_at)

    async def _update_feed_on_failure(
        self,
        feed: SourceFeed,
        now: datetime,
        exc: Exception,
    ) -> None:
        updated_feed = feed.model_copy(
            update={
                "last_polled_at": now,
                "last_error_summary": _failure_summary_from_exception(exc),
                "updated_at": now,
            }
        )
        async with session_scope(self._session_factory) as session:
            await upsert_source_feed(session, updated_feed)

    async def _update_feed_on_not_modified(self, feed: SourceFeed, now: datetime) -> None:
        updated_feed = feed.model_copy(
            update={
                "last_polled_at": now,
                "last_success_at": now,
                "last_error_summary": None,
                "updated_at": now,
            }
        )
        async with session_scope(self._session_factory) as session:
            await upsert_source_feed(session, updated_feed)

    async def _ingest_candidate(self, candidate: ArticleCandidate) -> IngestionResult:
        started_at = self._clock()

        try:
            canonical_url, fingerprint = canonicalize_url(
                candidate.url,
                block_private_networks=True,
            )
        except UrlValidationError as exc:
            return await self._record_failure(
                candidate,
                None,
                None,
                "invalid_url",
                str(exc),
                started_at,
            )

        duplicate_result = await self._check_duplicate(
            candidate, canonical_url, fingerprint, started_at
        )
        if duplicate_result is not None:
            return duplicate_result

        try:
            extracted = await self._primary_extractor.extract(canonical_url)
            if should_use_fallback(
                extracted,
                min_content_length=self._settings.article_min_content_length,
            ):
                try:
                    fallback_result = await self._fallback_extractor_if_safe(canonical_url)
                    if fallback_result is not None:
                        extracted = fallback_result
                except ExtractionFailedError:
                    pass
        except UrlValidationError as ssrf_exc:
            # The primary extractor's own SSRF check (e.g. a redirect resolving
            # to a private/loopback/reserved address) rejected this URL. That
            # rejection must be terminal, not a signal to retry through the
            # Crawl4AI fallback, which performs no host or redirect validation
            # of its own - falling back here would turn a blocked SSRF attempt
            # into a successful one via the weaker path.
            return await self._record_failure(
                candidate,
                canonical_url,
                fingerprint,
                "invalid_url",
                str(ssrf_exc),
                started_at,
            )
        except Exception as primary_exc:
            try:
                fallback_result = await self._fallback_extractor_if_safe(canonical_url)
                if fallback_result is None:
                    raise ExtractionFailedError(
                        f"fallback rejected re-validation for {canonical_url}"
                    )
                extracted = fallback_result
            except Exception as fallback_exc:
                return await self._record_failure(
                    candidate,
                    canonical_url,
                    fingerprint,
                    "extraction_failed",
                    (
                        f"primary extractor failed: {primary_exc}; "
                        f"fallback extractor failed: {fallback_exc}"
                    ),
                    started_at,
                )

        return await self._finalize_extracted(
            candidate, canonical_url, fingerprint, extracted, started_at
        )

    async def _check_duplicate(
        self,
        candidate: ArticleCandidate,
        url: str,
        fingerprint: str,
        started_at: datetime,
    ) -> IngestionResult | None:
        async with session_scope(self._session_factory) as session:
            existing = await get_article_by_fingerprint(session, fingerprint)
        if existing is None:
            return None
        return await self._record_duplicate(candidate, url, fingerprint, existing.id, started_at)

    async def _finalize_extracted(
        self,
        candidate: ArticleCandidate,
        canonical_url: str,
        fingerprint: str,
        extracted: ExtractedArticle,
        started_at: datetime,
    ) -> IngestionResult:
        title = (extracted.title or "").strip()
        if not title:
            return await self._record_failure(
                candidate,
                canonical_url,
                fingerprint,
                "missing_title",
                "extracted title is empty",
                started_at,
            )

        published_at = candidate.published_at or extracted.published_at
        if published_at is None:
            return await self._record_failure(
                candidate,
                canonical_url,
                fingerprint,
                "missing_published_at",
                "no reliable publication time from feed or page metadata",
                started_at,
            )

        cleaned_text = extracted.text.strip()
        if len(cleaned_text) < self._settings.article_min_content_length:
            return await self._record_failure(
                candidate,
                canonical_url,
                fingerprint,
                "content_too_short",
                (
                    f"cleaned content length {len(cleaned_text)} below minimum "
                    f"{self._settings.article_min_content_length}"
                ),
                started_at,
            )

        article = Article(
            source_id=candidate.source_id,
            url=canonical_url,
            url_fingerprint=fingerprint,
            title=title,
            author=candidate.author or extracted.author,
            published_at=published_at,
            language=extracted.language,
            raw_content_hash=extracted.raw_content_hash,
            cleaned_content=cleaned_text,
        )

        try:
            async with session_scope(self._session_factory) as session:
                await save_article(session, article)
                attempt = IngestionAttempt(
                    source_id=candidate.source_id,
                    source_feed_id=candidate.source_feed_id,
                    requested_url=candidate.url,
                    canonical_url=canonical_url,
                    url_fingerprint=fingerprint,
                    status=IngestionStatus.SUCCEEDED,
                    extractor=extracted.extractor,
                    article_id=article.id,
                    started_at=started_at,
                    completed_at=self._clock(),
                )
                await record_ingestion_attempt(session, attempt)
        except IntegrityError:
            async with session_scope(self._session_factory) as session:
                winner = await get_article_by_fingerprint(session, fingerprint)
                winner_id = winner.id if winner is not None else None
                attempt = IngestionAttempt(
                    source_id=candidate.source_id,
                    source_feed_id=candidate.source_feed_id,
                    requested_url=candidate.url,
                    canonical_url=canonical_url,
                    url_fingerprint=fingerprint,
                    status=IngestionStatus.DUPLICATE if winner_id else IngestionStatus.FAILED,
                    article_id=winner_id,
                    error_code=None if winner_id else "race_reload_failed",
                    started_at=started_at,
                    completed_at=self._clock(),
                )
                await record_ingestion_attempt(session, attempt)
            return IngestionResult(
                candidate_url=candidate.url,
                status=IngestionStatus.DUPLICATE if winner_id else IngestionStatus.FAILED,
                article_id=winner_id,
                error_code=None if winner_id else "race_reload_failed",
                error_summary=None
                if winner_id
                else "unique constraint violated but no winning article found on reload",
            )

        return IngestionResult(
            candidate_url=candidate.url,
            status=IngestionStatus.SUCCEEDED,
            article_id=article.id,
            error_code=None,
            error_summary=None,
        )

    async def _fallback_extractor_if_safe(self, canonical_url: str) -> ExtractedArticle | None:
        """Re-validate immediately before every Crawl4AI call, not just once upstream.

        Crawl4AIExtractor performs no host or redirect validation of its own, so
        this is the only SSRF check in effect for the fallback path. Re-checking
        right before the call (rather than trusting an earlier canonicalization)
        narrows the window for a DNS answer to change between the primary
        extractor's attempt and this one, and independently guards the
        short-content fallback trigger, which never went through a failure path
        at all. Returns None (not an exception) when re-validation fails, so
        callers can choose their own terminal-failure wording.
        """
        try:
            canonicalize_url(canonical_url, block_private_networks=True)
        except UrlValidationError:
            return None
        return await self._fallback_extractor.extract(canonical_url)

    async def _record_failure(
        self,
        candidate: ArticleCandidate,
        canonical_url: str | None,
        fingerprint: str | None,
        error_code: str,
        error_summary: str,
        started_at: datetime,
    ) -> IngestionResult:
        attempt = IngestionAttempt(
            source_id=candidate.source_id,
            source_feed_id=candidate.source_feed_id,
            requested_url=candidate.url,
            canonical_url=canonical_url,
            url_fingerprint=fingerprint,
            status=IngestionStatus.FAILED,
            error_code=error_code,
            error_summary=_sanitize_error_summary(error_summary),
            started_at=started_at,
            completed_at=self._clock(),
        )
        async with session_scope(self._session_factory) as session:
            await record_ingestion_attempt(session, attempt)
        return IngestionResult(
            candidate_url=candidate.url,
            status=IngestionStatus.FAILED,
            article_id=None,
            error_code=error_code,
            error_summary=attempt.error_summary,
        )

    async def _record_duplicate(
        self,
        candidate: ArticleCandidate,
        canonical_url: str,
        fingerprint: str,
        article_id: UUID,
        started_at: datetime,
    ) -> IngestionResult:
        attempt = IngestionAttempt(
            source_id=candidate.source_id,
            source_feed_id=candidate.source_feed_id,
            requested_url=candidate.url,
            canonical_url=canonical_url,
            url_fingerprint=fingerprint,
            status=IngestionStatus.DUPLICATE,
            article_id=article_id,
            started_at=started_at,
            completed_at=self._clock(),
        )
        async with session_scope(self._session_factory) as session:
            await record_ingestion_attempt(session, attempt)
        return IngestionResult(
            candidate_url=candidate.url,
            status=IngestionStatus.DUPLICATE,
            article_id=article_id,
            error_code=None,
            error_summary=None,
        )
