"""Bounded HTTP fetching with manual redirect validation and size limits."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from analyst_engine.ingestion.canonicalize import (
    canonicalize_url,
    resolve_validated_address,
)

MAX_REDIRECTS = 5

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_FORWARDED_RESPONSE_HEADERS = ("content-type", "etag", "last-modified")


class TooManyRedirectsError(RuntimeError):
    """Raised when a redirect chain exceeds the configured hop limit."""


class ResponseTooLargeError(RuntimeError):
    """Raised when a response body exceeds the configured size limit."""


class FetchTimeoutError(RuntimeError):
    """Raised when an HTTP request times out."""


class FetchNetworkError(RuntimeError):
    """Raised when an HTTP request fails due to a non-timeout network error."""


@dataclass(frozen=True)
class BoundedFetchResult:
    """Result of a bounded HTTP fetch."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    final_url: str


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for name in _FORWARDED_RESPONSE_HEADERS:
        value = headers.get(name)
        if value is not None:
            filtered[name] = value
    return filtered


def _build_request_headers(
    user_agent: str,
    extra_headers: dict[str, str] | None,
) -> dict[str, str]:
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _pin_to_validated_address(url: str) -> tuple[str, str]:
    """Return (url with host replaced by its just-validated IP, original hostname).

    canonicalize_url's own host check and the actual TCP connection httpx makes
    are two independent DNS lookups; an attacker controlling authoritative DNS
    for the target domain can answer them differently (DNS rebinding) and slip
    a private/internal address past validation. Resolving here and connecting
    directly to the returned IP - with the original hostname preserved via the
    Host header and TLS SNI extension for correct certificate validation -
    means the address actually connected to is the exact one just validated,
    with no further resolution in between.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    assert hostname is not None, "bounded_fetch always calls this on an already-canonicalized URL"
    pinned_ip = resolve_validated_address(hostname, block_private_networks=True)
    assert pinned_ip is not None, "block_private_networks=True always returns an IP or raises"
    netloc_host = f"[{pinned_ip}]" if ipaddress.ip_address(pinned_ip).version == 6 else pinned_ip
    netloc = netloc_host if parsed.port is None else f"{netloc_host}:{parsed.port}"
    pinned_url = urlunparse((parsed.scheme, netloc, parsed.path, "", parsed.query, ""))
    return pinned_url, hostname


async def _read_bounded_body(response: httpx.Response, size_limit_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > size_limit_bytes:
            raise ResponseTooLargeError(
                f"response body exceeds size limit of {size_limit_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def bounded_fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float,
    size_limit_bytes: int,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
) -> BoundedFetchResult:
    """Fetch a URL with SSRF-safe redirects, timeout, and response-size limits."""
    request_headers = _build_request_headers(user_agent, extra_headers)
    timeout = httpx.Timeout(timeout_seconds)
    current_url, _ = canonicalize_url(url, block_private_networks=True)

    for redirect_hops in range(MAX_REDIRECTS + 1):
        pinned_url, original_host = _pin_to_validated_address(current_url)
        hop_headers = dict(request_headers)
        hop_headers["Host"] = original_host
        try:
            async with client.stream(
                "GET",
                pinned_url,
                headers=hop_headers,
                follow_redirects=False,
                timeout=timeout,
                extensions={"sni_hostname": original_host},
            ) as response:
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if location is None:
                        raise FetchNetworkError(
                            f"redirect response missing Location header for {current_url}"
                        )
                    next_url = urljoin(current_url, location)
                    current_url, _ = canonicalize_url(
                        next_url,
                        block_private_networks=True,
                    )
                    if redirect_hops >= MAX_REDIRECTS:
                        raise TooManyRedirectsError(
                            f"exceeded maximum redirect hops ({MAX_REDIRECTS})"
                        )
                    continue

                body = await _read_bounded_body(response, size_limit_bytes)
                return BoundedFetchResult(
                    status_code=response.status_code,
                    headers=_filter_response_headers(response.headers),
                    body=body,
                    final_url=current_url,
                )
        except httpx.TimeoutException as exc:
            raise FetchTimeoutError(f"request timed out for {current_url}") from exc
        except httpx.NetworkError as exc:
            raise FetchNetworkError(f"network error fetching {current_url}") from exc

    raise TooManyRedirectsError(f"exceeded maximum redirect hops ({MAX_REDIRECTS})")
