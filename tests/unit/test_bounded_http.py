"""Offline unit tests for bounded HTTP fetching."""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from analyst_engine.ingestion.bounded_http import (
    MAX_REDIRECTS,
    BoundedFetchResult,
    FetchNetworkError,
    ResponseTooLargeError,
    TooManyRedirectsError,
    bounded_fetch,
)
from analyst_engine.ingestion.canonicalize import PrivateNetworkError, canonicalize_url

_USER_AGENT = "AnalystEngine-Test/0.1"
_TIMEOUT_SECONDS = 5.0


async def _fetch(
    handler: httpx.AsyncBaseTransport,
    url: str,
    *,
    size_limit_bytes: int = 1_000_000,
    extra_headers: dict[str, str] | None = None,
) -> BoundedFetchResult:
    async with httpx.AsyncClient(transport=handler) as client:
        return await bounded_fetch(
            client,
            url,
            timeout_seconds=_TIMEOUT_SECONDS,
            size_limit_bytes=size_limit_bytes,
            user_agent=_USER_AGENT,
            extra_headers=extra_headers,
        )


@pytest.mark.asyncio
async def test_bounded_fetch_returns_success_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == _USER_AGENT
        assert request.headers["if-none-match"] == '"etag-1"'
        return httpx.Response(
            200,
            headers={
                "content-type": "application/rss+xml",
                "etag": '"feed-etag"',
                "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
                "set-cookie": "ignored=yes",
            },
            content=b"<rss>ok</rss>",
            request=request,
        )

    result = await _fetch(
        httpx.MockTransport(handler),
        "https://93.184.216.34/feed.xml",
        extra_headers={"If-None-Match": '"etag-1"'},
    )

    assert result.status_code == 200
    assert result.body == b"<rss>ok</rss>"
    assert result.final_url == "https://93.184.216.34/feed.xml"
    assert result.headers == {
        "content-type": "application/rss+xml",
        "etag": '"feed-etag"',
        "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    }


@pytest.mark.asyncio
async def test_bounded_fetch_follows_redirect_chain_within_limit() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/next"},
                request=request,
            )
        return httpx.Response(200, content=b"final", request=request)

    result = await _fetch(httpx.MockTransport(handler), "https://93.184.216.34/start")

    assert result.status_code == 200
    assert result.body == b"final"
    assert result.final_url == "https://93.184.216.34/next"
    assert calls == [
        "https://93.184.216.34/start",
        "https://93.184.216.34/next",
    ]


@pytest.mark.asyncio
async def test_bounded_fetch_rejects_redirect_chain_exceeding_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        hop = int(request.url.path.removeprefix("/hop-"))
        return httpx.Response(
            302,
            headers={"location": f"/hop-{hop + 1}"},
            request=request,
        )

    with pytest.raises(TooManyRedirectsError, match=str(MAX_REDIRECTS)):
        await _fetch(httpx.MockTransport(handler), "https://93.184.216.34/hop-0")


@pytest.mark.asyncio
async def test_bounded_fetch_rejects_redirect_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(
        host: str,
        port: int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        assert host == "public.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async def handler(request: httpx.Request) -> httpx.Response:
        # The connection is pinned to the validated IP (93.184.216.34), but the
        # original hostname is preserved via the Host header - that's the fix
        # under test, so assert on the header, not request.url.host.
        if request.url.host == "93.184.216.34" and request.headers.get("host") == (
            "public.example"
        ):
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/internal"},
                request=request,
            )
        raise AssertionError(f"unexpected request to {request.url}")

    canonical, _ = canonicalize_url("https://public.example/start", block_private_networks=True)

    with pytest.raises(PrivateNetworkError, match="127.0.0.1"):
        await _fetch(httpx.MockTransport(handler), canonical)


@pytest.mark.asyncio
async def test_bounded_fetch_pins_connection_to_validated_ip_not_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual TCP/TLS connection must go to the IP just validated, not a
    fresh resolution of the hostname - otherwise an attacker controlling DNS
    for the target domain can answer the validation query safely and the
    connection-time query maliciously (DNS rebinding). Host header and TLS
    SNI must still carry the original hostname for correct routing/cert checks.
    """

    def fake_getaddrinfo(
        host: str,
        port: int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        assert host == "pinned.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, content=b"ok", request=request)

    canonical, _ = canonicalize_url("https://pinned.example/page", block_private_networks=True)

    await _fetch(httpx.MockTransport(handler), canonical)

    assert len(seen_requests) == 1
    sent = seen_requests[0]
    assert sent.url.host == "93.184.216.34"
    assert sent.headers.get("host") == "pinned.example"
    assert sent.extensions.get("sni_hostname") == "pinned.example"


@pytest.mark.asyncio
async def test_bounded_fetch_rejects_response_exceeding_size_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789", request=request)

    with pytest.raises(ResponseTooLargeError, match="size limit"):
        await _fetch(
            httpx.MockTransport(handler),
            "https://93.184.216.34/large",
            size_limit_bytes=5,
        )


@pytest.mark.asyncio
async def test_bounded_fetch_raises_network_error_when_redirect_missing_location() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request)

    with pytest.raises(FetchNetworkError, match="Location"):
        await _fetch(httpx.MockTransport(handler), "https://93.184.216.34/missing-location")
