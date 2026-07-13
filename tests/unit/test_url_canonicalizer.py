"""Offline unit tests for URL canonicalization and SSRF host validation."""

from __future__ import annotations

import hashlib
import socket
from typing import Any

import pytest

from analyst_engine.ingestion.canonicalize import (
    EmbeddedCredentialsError,
    InvalidHostError,
    PrivateNetworkError,
    UnsupportedSchemeError,
    canonicalize_url,
)


def _fingerprint(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode()).hexdigest()


def test_rejects_unsupported_schemes() -> None:
    with pytest.raises(UnsupportedSchemeError):
        canonicalize_url("file:///etc/passwd", block_private_networks=False)

    with pytest.raises(UnsupportedSchemeError):
        canonicalize_url("ftp://example.com/resource", block_private_networks=False)

    with pytest.raises(UnsupportedSchemeError):
        canonicalize_url("javascript:alert(1)", block_private_networks=False)


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(EmbeddedCredentialsError):
        canonicalize_url("http://user:pass@example.com/article", block_private_networks=False)

    with pytest.raises(EmbeddedCredentialsError):
        canonicalize_url("https://user@example.com/article", block_private_networks=False)


def test_strips_default_ports_and_normalizes_path() -> None:
    canonical, fingerprint = canonicalize_url(
        "HTTPS://Example.com:443/",
        block_private_networks=False,
    )

    assert canonical == "https://example.com/"
    assert fingerprint == _fingerprint(canonical)

    canonical_http, _ = canonicalize_url(
        "http://Example.com:80/path",
        block_private_networks=False,
    )
    assert canonical_http == "http://example.com/path"


def test_sorts_query_parameters_deterministically() -> None:
    canonical, fingerprint = canonicalize_url(
        "https://example.com/path?z=3&a=1&m=2&a=4#section",
        block_private_networks=False,
    )

    assert canonical == "https://example.com/path?a=1&a=4&m=2&z=3"
    assert fingerprint == _fingerprint(canonical)

    reordered, reordered_fingerprint = canonicalize_url(
        "https://example.com/path?m=2&z=3&a=1&a=4",
        block_private_networks=False,
    )
    assert reordered == canonical
    assert reordered_fingerprint == fingerprint


@pytest.mark.parametrize(
    ("url", "expected_fragment"),
    [
        ("http://127.0.0.1/", "127.0.0.1"),
        ("http://[::1]/", "::1"),
        ("http://169.254.169.254/", "169.254.169.254"),
        ("http://10.0.0.1/", "10.0.0.1"),
        ("http://172.16.0.1/", "172.16.0.1"),
        ("http://192.168.1.1/", "192.168.1.1"),
        ("http://0.0.0.0/", "0.0.0.0"),
    ],
)
def test_rejects_literal_private_and_reserved_ips(url: str, expected_fragment: str) -> None:
    with pytest.raises(PrivateNetworkError, match=expected_fragment):
        canonicalize_url(url, block_private_networks=True)


def test_rejects_dns_resolution_when_any_answer_is_private(
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
        assert host == "mixed.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.99", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(PrivateNetworkError, match="mixed.example"):
        canonicalize_url("https://mixed.example/article", block_private_networks=True)


def test_rejects_missing_host() -> None:
    with pytest.raises(InvalidHostError):
        canonicalize_url("http:///missing-host", block_private_networks=False)


def test_accepts_public_literal_ip_without_dns() -> None:
    canonical, fingerprint = canonicalize_url(
        "https://93.184.216.34/path",
        block_private_networks=True,
    )

    assert canonical == "https://93.184.216.34/path"
    assert fingerprint == _fingerprint(canonical)
