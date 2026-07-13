"""Offline unit tests for FeedClient."""

from __future__ import annotations

import httpx
import pytest

from analyst_engine.ingestion.feed_client import (
    FeedClient,
    RetryableFeedError,
    TerminalFeedError,
)

_USER_AGENT = "AnalystEngine-Test/0.1"
_TIMEOUT_SECONDS = 5.0
_SIZE_LIMIT_BYTES = 1_000_000
_FEED_URL = "https://93.184.216.34/feed.xml"


def _client(handler: httpx.AsyncBaseTransport) -> FeedClient:
    return FeedClient(
        httpx.AsyncClient(transport=handler),
        timeout_seconds=_TIMEOUT_SECONDS,
        size_limit_bytes=_SIZE_LIMIT_BYTES,
        user_agent=_USER_AGENT,
    )


@pytest.mark.asyncio
async def test_feed_client_returns_success_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == _USER_AGENT
        return httpx.Response(
            200,
            headers={
                "content-type": "application/rss+xml",
                "etag": '"feed-etag"',
                "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            },
            content=b"<rss>ok</rss>",
            request=request,
        )

    client = _client(httpx.MockTransport(handler))
    result = await client.fetch(_FEED_URL)

    assert result.status_code == 200
    assert result.not_modified is False
    assert result.raw_bytes == b"<rss>ok</rss>"
    assert result.etag == '"feed-etag"'
    assert result.last_modified == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert result.final_url == _FEED_URL


@pytest.mark.asyncio
async def test_feed_client_returns_not_modified_with_conditional_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"stored-etag"'
        assert request.headers["if-modified-since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
        return httpx.Response(
            304,
            headers={
                "etag": '"stored-etag"',
                "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            },
            request=request,
        )

    client = _client(httpx.MockTransport(handler))
    result = await client.fetch(
        _FEED_URL,
        etag='"stored-etag"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
    )

    assert result.status_code == 304
    assert result.not_modified is True
    assert result.raw_bytes is None
    assert result.etag == '"stored-etag"'
    assert result.last_modified == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert result.final_url == _FEED_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_feed_client_raises_retryable_error_for_transient_status(status_code: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(RetryableFeedError, match=f"retryable feed status {status_code}"):
        await client.fetch(_FEED_URL)


@pytest.mark.asyncio
async def test_feed_client_raises_terminal_error_for_client_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(TerminalFeedError, match="terminal feed status 404"):
        await client.fetch(_FEED_URL)


@pytest.mark.asyncio
async def test_feed_client_raises_terminal_error_for_oversized_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789", request=request)

    client = FeedClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=_TIMEOUT_SECONDS,
        size_limit_bytes=5,
        user_agent=_USER_AGENT,
    )

    with pytest.raises(TerminalFeedError, match="size limit"):
        await client.fetch(_FEED_URL)
