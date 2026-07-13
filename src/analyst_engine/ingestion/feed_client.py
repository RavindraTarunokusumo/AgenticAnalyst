"""Bounded HTTP feed fetching with conditional requests and classified errors."""

from __future__ import annotations

import httpx

from analyst_engine.ingestion.bounded_http import (
    FetchNetworkError,
    FetchTimeoutError,
    ResponseTooLargeError,
    TooManyRedirectsError,
    bounded_fetch,
)
from analyst_engine.ingestion.canonicalize import PrivateNetworkError, UrlValidationError
from analyst_engine.ingestion.models import FeedFetchResult


class FeedFetchError(RuntimeError):
    """Base error for feed fetch failures."""


class RetryableFeedError(FeedFetchError):
    """Raised when a feed fetch may succeed on retry."""


class TerminalFeedError(FeedFetchError):
    """Raised when a feed fetch should not be retried."""


class FeedClient:
    """Fetches RSS/Atom feeds with conditional requests and bounded HTTP."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float,
        size_limit_bytes: int,
        user_agent: str,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._size_limit_bytes = size_limit_bytes
        self._user_agent = user_agent

    async def fetch(
        self,
        feed_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedFetchResult:
        conditional_headers: dict[str, str] = {}
        if etag is not None:
            conditional_headers["If-None-Match"] = etag
        if last_modified is not None:
            conditional_headers["If-Modified-Since"] = last_modified

        try:
            result = await bounded_fetch(
                self._client,
                feed_url,
                timeout_seconds=self._timeout_seconds,
                size_limit_bytes=self._size_limit_bytes,
                user_agent=self._user_agent,
                extra_headers=conditional_headers or None,
            )
        except (FetchTimeoutError, FetchNetworkError) as exc:
            raise RetryableFeedError(str(exc)) from exc
        except (
            ResponseTooLargeError,
            TooManyRedirectsError,
            PrivateNetworkError,
            UrlValidationError,
        ) as exc:
            raise TerminalFeedError(str(exc)) from exc

        response_etag = result.headers.get("etag")
        response_last_modified = result.headers.get("last-modified")

        if result.status_code == 304:
            return FeedFetchResult(
                status_code=304,
                not_modified=True,
                etag=response_etag,
                last_modified=response_last_modified,
                final_url=result.final_url,
                raw_bytes=None,
            )

        if 200 <= result.status_code < 300:
            return FeedFetchResult(
                status_code=result.status_code,
                not_modified=False,
                etag=response_etag,
                last_modified=response_last_modified,
                final_url=result.final_url,
                raw_bytes=result.body,
            )

        if result.status_code == 429 or result.status_code >= 500:
            raise RetryableFeedError(f"retryable feed status {result.status_code} for {feed_url}")

        raise TerminalFeedError(f"terminal feed status {result.status_code} for {feed_url}")
